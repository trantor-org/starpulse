"""`starpulse backfill-links`: store each task's referenced pull requests as links, by today's ownership rule.

    starpulse backfill-links --config starpulse.toml

A task's `references` that name a pull request become a `delivers` link when `pull_requests.delivers` says the pull
request can be the task's delivery, else a `cites` link; a pull request that already delivers another task is a `cites`
link. A task that already holds a link to the pull request keeps it. The run prints one JSON line: `tasks`,
`pull_requests` (references read), `written`, `unchanged`, `delivers` and `cites` (the roles it wrote), `unmapped` (a
reference of a task with no UUID, or one no forge owns: written nowhere) and `mismatched` (a task whose links name other
pull requests than its references, with the `extra` links of each). A second run writes nothing. Stop `serve`
first for a run on the live store; a copy of the store takes the run the same way.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from starpulse.board.adapters.native_scan import native_keys
from starpulse.board.adapters.task_history import KIND
from starpulse.board.adapters.task_links import DeliveredElsewhere, TaskLinks
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore
from starpulse.pulls.adapters.outbound.github import GitHubAdapter, delivers
from starpulse.pulls.adapters.outbound.pull_requests import PULL_URL, pull_record
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.assembly import declared, history_store
from starpulse.runtime.config import ConfigError, discover, load

__all__ = ["main"]

REQUESTED_BY = "backfill:pull-request-links"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="starpulse backfill-links", description="store each task's referenced pull requests as links"
    )
    parser.add_argument("--config", type=Path, help="the TOML config the server runs with (default starpulse.toml)")
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (ConfigError, OSError, ValueError) as exc:
        parser.error(f"{path}: {exc}")
    board, machines, *_ = declared(config, path.parent if path else Path.cwd())
    keys = board.keys or native_keys()
    engine = history_store(config, path.parent if path else Path.cwd(), machines).engine
    forge, links, pulls = GitHubAdapter(keys=keys), TaskLinks(engine), PullStore(engine)
    report: dict = {"tasks": 0, "pull_requests": 0, "written": 0, "unchanged": 0, "delivers": 0, "cites": 0, "unmapped": [], "mismatched": []}
    events = EventStore(engine)
    for task in sorted(events.heads(KIND)):
        row = replay(events.read(KIND, task))
        report["tasks"] += 1
        uuid, urls = str((row.get("meta") or {}).get("uuid") or ""), list(dict.fromkeys(ref for ref in row["references"] if PULL_URL.fullmatch(ref)))
        report["pull_requests"] += len(urls)
        refs: dict[str, str] = {}
        for url in urls:
            try:
                named = forge.change_ref(url)
            except ValueError:
                named = None
            if named is None or not uuid:
                report["unmapped"].append({"task": task, "ref": url})
            else:
                refs[url] = f"change:{named.adapter}:{named.id}"
        if not uuid:
            continue
        held = links.refs(uuid)
        for url, ref in refs.items():
            if ref in held:
                report["unchanged"] += 1
                continue
            role = "delivers" if delivers(pull_record(pulls, url), task, keys) else "cites"
            try:
                links.put(uuid, role, ref, REQUESTED_BY)
            except DeliveredElsewhere:
                role = "cites"
                links.put(uuid, role, ref, REQUESTED_BY)
            report["written"] += 1
            report[role] += 1
        if extra := links.refs(uuid) - set(refs.values()):
            report["mismatched"].append({"task": task, "extra": sorted(extra)})
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
