"""The GitHub adapter: a pull request and its check runs become events on the pull-request machine.

Events arrive through the App webhook, which hands the recorded pull request and its check runs to `GitHubAdapter.events`.
The adapter depends on nothing of a host project's: not its hooks, its `AGENTS.md` or its branch names.
"""

from dataclasses import dataclass
from pathlib import Path

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.stamps import epoch_of
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
        """The events `bundle` (`pull` and `check_runs`, as GitHub answers them) moves the machines by, oldest first."""
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
