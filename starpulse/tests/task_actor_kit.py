"""Fakes for the task actor tests: a board whose editor applies each status change to the feed, and pull records."""

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from starpulse._internal.board.seam import Written
from starpulse._internal.config.config import Repo
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.pulls.pulls import PullStore
from starpulse._internal.pulls.task_actor import TaskActor
from starpulse.contracts.adapters import BoardTask

PR_ONE = "https://github.com/acme/trantor/pull/1"
PR_TWO = "https://github.com/acme/trantor/pull/2"
SHA = "a" * 40
WAITS = {
    "review": {"pr_terminal": "MERGED"},
    "waiting": {"deps_done": "DEPS_DONE"},
    "ready": {"deps_unresolved": "WAIT_ON_DEPS"},
}
MOVES = {("review", "MERGED"): "done", ("waiting", "DEPS_DONE"): "ready", ("ready", "WAIT_ON_DEPS"): "waiting"}
WITHIN_S = 1.0
CHILD, PARENT = "c" * 40, "p" * 40
CHILD_PR = "https://github.com/acme/starpulse/pull/10"
REPOS = [Repo(name="starpulse", path="starpulse", applied_by="pin-bump")]


class Pins:
    """The parent's pointer reads: `main`'s bump pins `CHILD` at `starpulse`; a child contains a commit it equals."""

    def pointer(self, repo: str, sha: str, path: str) -> str | None:
        return CHILD if (repo, sha, path) == ("acme/trantor", PARENT, "starpulse") else None

    def reaches(self, repo: str, sha: str, pointer: str) -> bool:
        return sha == pointer


class Board:
    """A board whose editor applies each status change to the feed, as the board's poll places a written file."""

    def __init__(self, feed: BoardFeed, *tasks: BoardTask) -> None:
        self.feed = feed
        self.tasks = {each.id: each for each in tasks}
        self.writes: list[tuple[str, Mapping[str, Any], str | Sequence[str], str]] = []
        self.refuse = False
        for each in tasks:
            feed.put(each)

    def put(self, each: BoardTask) -> None:
        self.tasks[each.id] = each
        self.feed.put(each)

    def edit(self, name: str, changes: Mapping[str, Any], comment: str | Sequence[str], /, actor: str = "") -> Written:
        self.writes.append((name, changes, comment, actor))
        if self.refuse:
            return Written(False, f"{name}: refused")
        self.put(self.tasks[name].model_copy(update={"lane": changes["status"]}))
        return Written(True, name)

    def moved(self) -> list[tuple[str, str]]:
        return [(name, changes["status"]) for name, changes, _, _ in self.writes]


def pull(
    number: int, *, state: str, repo: str = "acme/trantor", sha: str = SHA, files: Sequence[str] = ()
) -> dict:
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


def running(board: Board, store: PullStore, stop: threading.Event, **settle: Any) -> TaskActor:
    """An actor over `board` that has derived every open task once."""
    actor = TaskActor(board.feed, store, board.edit, WAITS, MOVES, **settle)
    actor.start(stop)
    assert actor.ready.wait(WITHIN_S)
    return actor
