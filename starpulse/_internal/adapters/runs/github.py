"""The GitHub adapter: a repository's pull requests, checks and Copilot work become events on two machines.

    python -m starpulse._internal.adapters.runs.github --repo OWNER/NAME [--interval 300] [--config FILE] [--key RE --branch RE --key-format FMT]

Every `--interval` seconds it reads the repository's 30 most recently updated pull requests and appends their events
to the event log in the database `--config` names (default `starpulse.toml` in the working directory), the store
`starpulse serve` reads. Reads are signed in with `GITHUB_TOKEN` or `GH_TOKEN` when one is set; without, GitHub's lower
unauthenticated rate limit applies. A second read of a pull request appends nothing new: each event's id is derived
from the GitHub record behind it.

The `github-pull-request` machine follows a pull request: opened, its checks passing or failing, merged or closed. The
`copilot` machine follows Copilot on it: the `copilot_work_started` and `copilot_work_finished` timeline events (the
actor is the person who asked), the `dynamic` workflow runs GitHub names "Running Copilot cloud agent" and "Running
Copilot Code Review", and reviews by `copilot-pull-request-reviewer[bot]`. An event is keyed by the task the pull
request's branch names under the adapter's `TaskKeys`, else by the pull request itself (`owner/name#7`). GitHub exposes
no per-tool trajectory for Copilot sessions, so these are spans and outcomes, not trajectories.

GitHub documents neither Copilot timeline event name; the recorded fixtures in the tests pin them, so a rename fails
the adapter's tests rather than the page.

The adapter depends on nothing of trantor's: not its hooks, its `AGENTS.md` or its branch names.
"""

from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from starpulse._internal.adapters.runs.github_actions import Transport, _get, connect, repo_of
from starpulse.contracts.adapters import TaskKeys
from starpulse._internal.domain.machine_definition import load_machine
from starpulse._internal.domain.snapshot import describe
from starpulse._internal.store import events as machine_events
from starpulse._internal.store.event_log import EventLog
from starpulse._internal.store.history import open_event_log

#: The machine files beside the package: `adapters/runs/` is two levels below them.
MACHINES = Path(__file__).parents[3] / "machines"
PULL_REQUEST = load_machine(MACHINES / "github-pull-request.yaml")
COPILOT = load_machine(MACHINES / "copilot.yaml")
GITHUB_MACHINES = {m.name: describe(m.machine) for m in (PULL_REQUEST, COPILOT)}


#: The timeline events GitHub records when Copilot's coding agent starts and stops work on a pull request; the actor is
#: the person who asked. GitHub documents neither name.
_TIMELINE = {"copilot_work_started": "WORK_STARTED", "copilot_work_finished": "WORK_FINISHED"}
#: The `dynamic` workflow runs Copilot's own sessions appear as, by run name: the events a run's start and end become.
_RUNS = {
    "Running Copilot cloud agent": ("RUN_STARTED", "RUN_FINISHED"),
    "Running Copilot Code Review": ("REVIEW_RUN_STARTED", "REVIEW_RUN_FINISHED"),
}
#: The bot that submits Copilot's code reviews.
REVIEWER = "copilot-pull-request-reviewer[bot]"
#: The conclusions of a completed check run that leave the rollup passing.
_PASSING = frozenset({"success", "neutral", "skipped"})


def _epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp()


@dataclass(frozen=True)
class GitHubAdapter:
    """Maps one pull request's recorded GitHub data onto `MachineEvent` dicts for `keys`' task scheme.

    An event is keyed by the task the pull request's branch names, else by the pull request as a run (`owner/name#7`).
    Each carries an `event_id` derived from the GitHub record behind it, so reading a pull request again appends nothing.
    """

    keys: TaskKeys

    def events(self, repo: str, bundle: dict) -> list[dict]:
        """The events `bundle` (`pull`, `timeline`, `reviews`, `check_runs`, `runs`, as `read` returns it) moves the machines by, oldest first."""
        pull = bundle["pull"]
        pr = f"{repo}#{pull['number']}"
        task = self.keys.for_branch(pull["head"]["ref"])

        def event(machine: str, name: str, actor: str, stamp: str, source: object) -> dict:
            return {
                "event_id": f"github:{pr}:{machine}:{name}:{source}",
                "machine": machine,
                "event": name,
                "task": task,
                "run": None if task else pr,
                "actor": actor,
                "time": _epoch(stamp),
            }

        events = [event("github-pull-request", "PR_OPENED", pull["user"]["login"], pull["created_at"], "")]
        for item in bundle["timeline"]:
            if name := _TIMELINE.get(item["event"]):
                events.append(event("copilot", name, item["actor"]["login"], item["created_at"], item["id"]))
        for run in bundle["runs"]["workflow_runs"]:
            if run["event"] == "dynamic" and run["name"] in _RUNS:
                started, finished = _RUNS[run["name"]]
                events.append(event("copilot", started, "copilot", run["created_at"], run["id"]))
                if run["status"] == "completed":
                    events.append(event("copilot", finished, "copilot", run["updated_at"], run["id"]))
        for review in bundle["reviews"]:
            if review["user"]["login"] == REVIEWER:
                events.append(event("copilot", "REVIEW_SUBMITTED", REVIEWER, review["submitted_at"], review["id"]))
        checks = bundle["check_runs"]["check_runs"]
        if checks and all(check["status"] == "completed" for check in checks):
            passed = all(check["conclusion"] in _PASSING for check in checks)
            name = "CHECKS_PASSED" if passed else "CHECKS_FAILED"
            events.append(
                event(
                    "github-pull-request", name, "github", max(c["completed_at"] for c in checks), pull["head"]["sha"]
                )
            )
        if pull["merged_at"]:
            events.append(event("github-pull-request", "PR_MERGED", "github", pull["merged_at"], ""))
        elif pull["closed_at"]:
            events.append(event("github-pull-request", "PR_CLOSED", "github", pull["closed_at"], ""))
        return sorted(events, key=lambda e: e["time"])


#: GitHub's page size; a page shorter than it is the last.
_PAGE = 100
#: The most pages read of one list, so a pull request with a very long timeline cannot spend the rate limit.
_MAX_PAGES = 10


def _items(transport: Transport, path: str) -> list[dict]:
    """Every item of the list endpoint `path` (which carries `?per_page=100`), page by page."""
    items: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        got = _get(transport, f"{path}&page={page}")["items"]
        items += got
        if len(got) < _PAGE:
            break
    return items


def read(transport: Transport, repo: str, number: int) -> dict:
    """Pull request `number` of `repo` as `GitHubAdapter.events` takes it: the pull, its timeline, its reviews, the check
    runs of its head commit and the workflow runs of its branch, each as GitHub answers."""
    base = f"/repos/{repo}"
    pull = _get(transport, f"{base}/pulls/{number}")
    return {
        "pull": pull,
        "timeline": _items(transport, f"{base}/issues/{number}/timeline?per_page={_PAGE}"),
        "reviews": _items(transport, f"{base}/pulls/{number}/reviews?per_page={_PAGE}"),
        "check_runs": _get(transport, f"{base}/commits/{pull['head']['sha']}/check-runs?per_page={_PAGE}"),
        "runs": _get(transport, f"{base}/actions/runs?branch={quote(pull['head']['ref'], safe='')}&per_page={_PAGE}"),
    }


#: How many of a repository's most recently updated pull requests one poll reads.
RECENT = 30


def poll(transport: Transport, repo: str, adapter: GitHubAdapter, log: EventLog, seen: dict[int, str]) -> None:
    """Append the events of `repo`'s recently updated pull requests to `log`.

    An open pull request is read every poll, since its checks finish without touching its update time; a closed one only
    when its `updated_at` is not the one `seen` holds. An event already in the log is not appended again.
    """
    listed = _get(transport, f"/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page={RECENT}")["items"]
    for pull in listed:
        if pull["state"] != "open" and seen.get(pull["number"]) == pull["updated_at"]:
            continue
        for event in adapter.events(repo, read(transport, repo, pull["number"])):
            fields = {k: v for k, v in event.items() if k != "event_id" and v is not None}
            log.append(machine_events.STREAM, fields, event_id=event["event_id"])
        seen[pull["number"]] = pull["updated_at"]


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — polling process boundary
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--repo", required=True, help="the repository to read, `owner/name` or its URL")
    parser.add_argument("--interval", type=float, default=300.0, help="seconds between reads")
    parser.add_argument("--config", type=Path, help="the TOML config whose database holds the event log")
    parser.add_argument("--key", default=r"TASK-\d+", help="a whole task key")
    parser.add_argument(
        "--branch", default=r"(?i)(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", help="group 1 names the key"
    )
    parser.add_argument("--key-format", default="TASK-{}", help="wraps the branch's group 1 into the key")
    args = parser.parse_args(argv)
    keys = TaskKeys(key=re.compile(args.key), branch=re.compile(args.branch), key_format=args.key_format)
    try:
        log = open_event_log(args.config)
    except (OSError, ValueError) as exc:
        parser.error(f"{args.config or 'starpulse.toml'}: {exc}")

    repo = repo_of(args.repo)
    transport = connect(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    adapter, seen = GitHubAdapter(keys), {}
    print(f"github adapter reading {repo} every {args.interval:g}s", flush=True)
    while True:
        try:
            poll(transport, repo, adapter, log, seen)
        except OSError as exc:  # GitHub unreachable or refused: the next poll tries again
            print(f"github adapter: {exc}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
