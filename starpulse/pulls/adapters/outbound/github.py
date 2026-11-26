"""The GitHub adapter: a pull request and its check runs become events on the pull-request machine.

Events arrive through the App webhook, which hands the recorded pull request and its check runs to `GitHubAdapter.events`.
The adapter depends on nothing of a host project's: not its hooks, its `AGENTS.md` or its branch names.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from starpulse.contracts.adapters import ChangeRef, TaskKeys
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
#: A pull request's page path: `owner/name/pull/7`, with any tab after the number.
_PULL_PATH = re.compile(r"/([\w.-]+/[\w.-]+)/pull/(\d+)(?:/.*)?", re.ASCII)
#: A change reference's id as `change_ref` writes it: `owner/name:7`.
_CHANGE_ID = re.compile(r"([\w.-]+/[\w.-]+):(\d+)", re.ASCII)
#: A word of a pull request's title, to match against a task key.
_WORD = re.compile(r"[\w-]+(?:\.[\w-]+)*")


def named_tasks(record: Mapping[str, object], keys: TaskKeys) -> set[str]:
    """The tasks a pull request's title and branch name: the one-time import of the links a task never wrote reads them."""
    whole = re.compile(keys.key.pattern, keys.key.flags | re.I)
    titled = {word.lower() for word in _WORD.findall(str(record.get("title") or "")) if whole.fullmatch(word)}
    branch = keys.for_branch(str(record.get("headRefName") or "") or None)
    return titled | ({branch.lower()} if branch else set())


def delivers(record: Mapping[str, object] | None, task_id: str, keys: TaskKeys) -> bool:
    """Whether a pull request can be `task_id`'s delivery: one whose branch or title names tasks and not this one is
    another task's, a reference only."""
    named = named_tasks(record, keys) if record else set()
    return not named or task_id.lower() in named


def urls_of(forges: Mapping[str, "GitHubAdapter"]) -> Callable[[str], str | None]:
    """A stored link's reference as the page of the change it names; None for one no configured forge owns."""

    def url(ref: str) -> str | None:
        kind, _, rest = ref.partition(":")
        instance, _, identity = rest.partition(":")
        if kind != "change" or (forge := forges.get(instance)) is None:
            return None
        try:
            return forge.change_url(ChangeRef(adapter=instance, id=identity))
        except ValueError:
            return None

    return url


@dataclass(frozen=True)
class GitHubAdapter:
    """Maps one pull request's recorded GitHub data onto `MachineEvent` dicts for `keys`' task scheme.

    An event is keyed by the task the pull request's branch names, else by the pull request as a run (`owner/name#7`).
    Each carries an `event_id` derived from the GitHub record behind it, so reading a pull request again appends nothing.
    """

    keys: TaskKeys
    instance: str = "github"

    def change_ref(self, url: str) -> ChangeRef:
        """The reference of the pull request at `url`; ValueError names why a URL is not one this adapter owns."""
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != "github.com":
            raise ValueError(
                f"{url!r} is on {parts.hostname or 'no host'} over {parts.scheme or 'no scheme'}, and only https://github.com is a configured forge"
            )
        if not (pull := _PULL_PATH.fullmatch(parts.path)):
            raise ValueError(f"{url!r} is not a pull request URL (https://github.com/<owner>/<repo>/pull/<number>)")
        return ChangeRef(adapter=self.instance, id=f"{pull[1]}:{pull[2]}")

    def change_url(self, ref: ChangeRef) -> str:
        """The page of the pull request `ref` names; ValueError when another adapter instance owns it."""
        if ref.adapter != self.instance:
            raise ValueError(f"{ref.adapter!r} owns this pull request, not the {self.instance!r} adapter")
        if not (pull := _CHANGE_ID.fullmatch(ref.id)):
            raise ValueError(f"{ref.id!r} is a malformed pull request id (owner/name:number)")
        return f"https://github.com/{pull[1]}/pull/{pull[2]}"

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
