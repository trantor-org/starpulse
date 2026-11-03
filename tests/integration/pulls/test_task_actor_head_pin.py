"""A pin pushed to the parent's default branch with no bump PR releases the dependent of a merged child PR."""

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.pulls.adapters.outbound.github import GitHub
from starpulse.runtime.adapter_kit import task

from tests.task_actor_kit import CHILD, CHILD_PR, REPOS, Board, pull, running, until

TIP, POINTER = "t" * 40, "d" * 40
HEAD = "repos/acme/trantor/commits/HEAD"
AT_TIP = f"repos/acme/trantor/contents/starpulse?ref={TIP}"
CONTAINS = f"repos/acme/starpulse/compare/{CHILD}...{POINTER}"
NO_BUMP = "no merged bump pins it"


class Gh:
    """A GitHub transport: each endpoint's answer; an endpoint in `down` fails the way an expired token does."""

    def __init__(self) -> None:
        self.answers = {HEAD: {"sha": TIP}, AT_TIP: {"sha": POINTER}, CONTAINS: {"status": "ahead"}}
        self.down: set[str] = set()

    def __call__(self, method: str, path: str, body: dict | None) -> tuple[int, dict]:
        if path in self.down or path not in self.answers:
            return 401, {}
        return 200, self.answers[path]


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


@pytest.fixture
def gh() -> Gh:
    return Gh()


def _board() -> Board:
    return Board(
        BoardFeed(),
        task("TASK-1", "Done", references=(CHILD_PR,)),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )


def test_a_pin_on_the_default_branch_with_no_bump_pr_releases_the_dependent(
    store: PullStore, stop: threading.Event, gh: Gh
) -> None:
    board = _board()
    store.save([pull(10, state="MERGED", repo="acme/starpulse", sha=CHILD), pull(2, state="OPEN")])
    actor = running(board, store, stop, repos=REPOS, pin_rule="pin-bump", pins=GitHub(transport=gh))

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
    assert "\nstarpulse_task_actor_pin_held 0\n" in actor.exposition()


def test_a_github_failure_holds_the_dependent_naming_the_failed_call_until_it_answers(
    store: PullStore, stop: threading.Event, gh: Gh, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    gh.down = {HEAD}
    board = _board()
    store.save([pull(10, state="MERGED", repo="acme/starpulse", sha=CHILD), pull(2, state="OPEN")])
    actor = running(board, store, stop, repos=REPOS, pin_rule="pin-bump", pins=GitHub(transport=gh))

    held = [comment for _, comment in board.comments() if "Held from Ready" in comment]
    assert board.moved() == []
    assert len(held) == 1
    assert HEAD in held[0]
    assert NO_BUMP not in held[0]

    gh.down.clear()
    clock[0] += 61
    store.save([pull(3, state="OPEN")])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
