"""Fakes for the task actor tests: a board whose editor applies each status change to the feed, and pull records."""

import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from starpulse.board.board_feed import BoardFeed
from starpulse.board.criteria import authored
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import BoardTask
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.pulls.pins import Repo
from starpulse.pulls.pulls import PullStore
from starpulse.pulls.task_actor import TaskActor

PR_ONE = "https://github.com/acme/trantor/pull/1"
PR_TWO = "https://github.com/acme/trantor/pull/2"
SHA = "a" * 40
WAITS = {
    "in_progress": {"pr_ready": "REVIEW"},
    "review": {"pr_terminal": "MERGED"},
    "waiting": {"deps_done": "DEPS_DONE", "criteria_met": "CRITERIA_MET"},
    "ready": {"deps_unresolved": "WAIT_ON_DEPS", "criteria_unmet": "CRITERIA_UNMET"},
}
ROLES = StateRoles(
    {
        "new": "initial",
        "ready": "waiting_on_fact",
        "waiting": "waiting_on_fact",
        "in_progress": "waiting_on_fact",
        "review": "waiting_on_fact",
        "needs_attention": "waiting_on_person",
        "done": "resting",
        "archived": "final",
    },
    WAITS,
    ("done",),
)
MOVES = {
    ("in_progress", "REVIEW"): "review",
    ("review", "MERGED"): "done",
    ("waiting", "DEPS_DONE"): "ready",
    ("ready", "WAIT_ON_DEPS"): "waiting",
    ("waiting", "CRITERIA_MET"): "ready",
    ("ready", "CRITERIA_UNMET"): "waiting",
}
WITHIN_S = 1.0
CHILD, PARENT = "c" * 40, "p" * 40
CHILD_PR = "https://github.com/acme/starpulse/pull/10"
REPOS = [Repo(name="starpulse", path="starpulse", applied_by="pin-bump")]
#: A description whose Start Criteria declare one criterion, `soak`.
GATED = (
    "## Start Criteria\n\n```yaml\nstart_criteria:\n  - id: soak\n    kind: prom\n    expr: up\n    at_least: 1\n```\n"
)


class Criteria:
    """An evaluator that answers each criterion with `status` and counts how often it was asked, per task."""

    def __init__(self, status: str) -> None:
        self.status = status
        self.asked: Counter[str] = Counter()

    def __call__(self, task: str, description: str) -> list[dict[str, Any]]:
        self.asked[task] += 1
        error = "cannot reach prometheus" if self.status == "error" else None
        return [
            {**each, "status": self.status, "observed": None, "error": error, "checked": None}
            for each in authored(description)
        ]


class Pins:
    """The parent's pointer reads: `main`'s bump pins `CHILD` at `starpulse`; a child contains a commit it equals."""

    def pointer(self, repo: str, sha: str, path: str) -> str | None:
        return CHILD if (repo, sha, path) == ("acme/trantor", PARENT, "starpulse") else None

    def reaches(self, repo: str, sha: str, pointer: str) -> bool:
        return sha == pointer

    def head(self, repo: str) -> str | None:
        return None


class Board:
    """A board whose editor applies each status change to the feed, as the board's poll places a written file."""

    def __init__(self, feed: BoardFeed, *tasks: BoardTask) -> None:
        self.feed = feed
        self.tasks = {each.id: each for each in tasks}
        self.writes: list[tuple[str, Mapping[str, Any], str | Sequence[str], str]] = []
        self.refuse = False
        #: The refusal the board gives a status change into each lane named here.
        self.refusing: dict[str, str] = {}
        #: The refusal a declared guard or validate hook gives a status change into each lane named here.
        self.linting: dict[str, str] = {}
        for each in tasks:
            feed.put(each)

    def put(self, each: BoardTask) -> None:
        self.tasks[each.id] = each
        self.feed.put(each)

    def edit(self, name: str, changes: Mapping[str, Any], comment: str | Sequence[str], /, actor: str = "") -> Written:
        self.writes.append((name, changes, comment, actor))
        if self.refuse:
            return Written(False, f"{name}: refused")
        if changes.get("status") in self.linting:
            return Written(False, self.linting[changes["status"]], lint=True)
        if changes.get("status") in self.refusing:
            return Written(False, self.refusing[changes["status"]])
        if "status" in changes:
            self.put(self.tasks[name].model_copy(update={"lane": changes["status"]}))
        return Written(True, name)

    def moved(self) -> list[tuple[str, str]]:
        return [(name, changes["status"]) for name, changes, _, _ in self.writes if "status" in changes]

    def comments(self) -> list[tuple[str, str]]:
        """The comments written without a move."""
        return [(name, str(comment)) for name, changes, comment, _ in self.writes if not changes]


def pull(number: int, *, state: str, repo: str = "acme/trantor", sha: str = SHA, files: Sequence[str] = ()) -> dict:
    at, sha = ("2026-10-12T09:00:00Z", sha) if state == "MERGED" else (None, None)
    return {
        "repo": repo,
        "number": number,
        "state": state,
        "isDraft": False,
        "mergeable": "UNKNOWN",
        "baseRefName": "main",
        "headRefOid": f"{number:040x}",
        "body": "",
        "checks": "pass",
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": at or "2026-10-12T08:00:00Z",
        "mergedAt": at,
        "mergeSha": sha,
        "fetchedAt": 0.0,
        "detail": {"mergedAt": at, "mergeSha": sha, "behindMain": 0, "files": list(files), "ci": {}},
    }


def until(condition: Callable[[], bool], within: float = WITHIN_S) -> bool:
    """Whether `condition` came true within `within` seconds."""
    deadline = time.monotonic() + within
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    return condition()


def running(board: Board, store: PullStore, stop: threading.Event, **options: Any) -> TaskActor:
    """An actor over `board` that has derived every open task once."""
    actor = TaskActor(board.feed, store, board.edit, WAITS, MOVES, **options)
    actor.start(stop)
    assert actor.ready.wait(WITHIN_S)
    return actor
