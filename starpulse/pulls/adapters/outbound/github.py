"""The GitHub adapter: a repository's pull requests and their checks become events on the pull-request machine.

    python -m starpulse.cli.github_adapter --repo OWNER/NAME [--interval 300] [--config FILE] [--key RE --branch RE --key-format FMT]

Every `--interval` seconds it reads the repository's 30 most recently updated pull requests and appends their events
to the event log in the database `--config` names (default `starpulse.toml` in the working directory), the store
`starpulse serve` reads. Reads are signed in with `GITHUB_TOKEN` or `GH_TOKEN` when one is set; without, GitHub's lower
unauthenticated rate limit applies. A second read of a pull request appends nothing new: each event's id is derived
from the GitHub record behind it.

The `github-pull-request` machine follows a pull request: opened, its checks passing or failing, merged or closed. An
event is keyed by the task the pull request's branch names under the adapter's `TaskKeys`, else by the pull request
itself (`owner/name#7`).

The adapter depends on nothing of a host project's: not its hooks, its `AGENTS.md` or its branch names.
"""

import argparse
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.stamps import epoch_of
from starpulse.event_log import events as machine_events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import open_event_log
from starpulse.github.adapters.outbound.rest import Transport, connect, get, repo_of
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.snapshot import describe

#: The machine files beside the package: `adapters/runs/` is two levels below them.
MACHINES = Path(__file__).parents[3] / "machines"
PULL_REQUEST = load_machine(MACHINES / "github-pull-request.yaml")
CI_JOB = load_machine(MACHINES / "ci-job.yaml")
PR_CHECKS = load_machine(MACHINES / "pr-checks.yaml")
GITHUB_MACHINES = {m.name: describe(m.machine) for m in (PULL_REQUEST, CI_JOB, PR_CHECKS)}


#: The conclusions of a completed check run that leave the rollup passing.
_PASSING = frozenset({"success", "neutral", "skipped"})


@dataclass(frozen=True)
class GitHubAdapter:
    """Maps one pull request's recorded GitHub data onto `MachineEvent` dicts for `keys`' task scheme.

    An event is keyed by the task the pull request's branch names, else by the pull request as a run (`owner/name#7`).
    Each carries an `event_id` derived from the GitHub record behind it, so reading a pull request again appends nothing.
    """

    keys: TaskKeys

    def events(self, repo: str, bundle: dict) -> list[dict]:
        """The events `bundle` (`pull` and `check_runs`, as `read` returns it) moves the machines by, oldest first."""
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
                "time": epoch_of(stamp),
            }

        events = [event("github-pull-request", "PR_OPENED", pull["user"]["login"], pull["created_at"], "")]
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


#: The page of check runs one read takes; GitHub's largest page.
_PAGE = 100


def read(transport: Transport, repo: str, number: int) -> dict:
    """Pull request `number` of `repo` as `GitHubAdapter.events` takes it: the pull and the check runs of its head commit,
    each as GitHub answers."""
    pull = get(transport, f"/repos/{repo}/pulls/{number}")
    return {
        "pull": pull,
        "check_runs": get(transport, f"/repos/{repo}/commits/{pull['head']['sha']}/check-runs?per_page={_PAGE}"),
    }


#: How many of a repository's most recently updated pull requests one poll reads.
RECENT = 30


def poll(transport: Transport, repo: str, adapter: GitHubAdapter, log: EventLog, seen: dict[int, str]) -> None:
    """Append the events of `repo`'s recently updated pull requests to `log`.

    An open pull request is read every poll, since its checks finish without touching its update time; a closed one only
    when its `updated_at` is not the one `seen` holds. An event already in the log is not appended again.
    """
    listed = get(transport, f"/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page={RECENT}")["items"]
    for pull in listed:
        if pull["state"] != "open" and seen.get(pull["number"]) == pull["updated_at"]:
            continue
        for event in adapter.events(repo, read(transport, repo, pull["number"])):
            fields = {k: v for k, v in event.items() if k != "event_id" and v is not None}
            log.publish(machine_events.STREAM, fields, event_id=event["event_id"])
        seen[pull["number"]] = pull["updated_at"]


def main(
    argv: list[str] | None = None,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], Any],
) -> None:  # pragma: no mutate block — polling process boundary
    """Poll the repository; `discover` and `load` read the root config, which the runtime owns and passes in."""
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
        path = discover(args.config)
        log = open_event_log(load(path).database_url, path)
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
