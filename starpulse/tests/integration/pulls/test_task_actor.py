"""The task actor moves a task on the facts its lane waits on, as `starpulse/task-actor`, through the board's editor."""

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pulls import PullStore
from starpulse._internal.pulls.task_actor import ACTOR
from starpulse.tests.task_actor_kit import (
    CHILD,
    CHILD_PR,
    PARENT,
    PR_ONE,
    PR_TWO,
    REPOS,
    SHA,
    WITHIN_S,
    Board,
    Pins,
    pull,
    running,
    until,
)


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def test_a_review_task_whose_only_pr_merged_moves_to_done_and_no_other_task_is_derived(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", references=(PR_ONE,)),
        task("TASK-2", "Review", references=(PR_TWO,)),
        task("TASK-3", "Ready"),
    )
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN")])
    actor = running(board, store, stop)
    derived = dict(actor.derivations)
    store.save([pull(1, state="MERGED")])

    projected = time.monotonic()
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert time.monotonic() - projected < WITHIN_S
    name, changes, comment, actor_name = board.writes[0]
    assert (changes, actor_name) == ({"status": "done"}, ACTOR)
    assert f"acme/trantor#1 merged as {SHA}" in str(comment)
    assert {name: count - derived[name] for name, count in actor.derivations.items()} == {"TASK-1": 1, "TASK-2": 0, "TASK-3": 0}


def test_a_waiting_task_moves_to_ready_when_its_last_dependency_enters_done(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Done"),
        task("TASK-2", "In Progress"),
        task("TASK-3", "Waiting", dependencies=("TASK-1", "TASK-2")),
    )
    running(board, store, stop)
    assert board.moved() == []

    board.put(task("TASK-2", "Done"))

    assert until(lambda: board.moved() == [("TASK-3", "ready")])
    assert board.writes[0][3] == ACTOR


def test_a_ready_task_with_an_unresolved_dependency_moves_to_waiting(store: PullStore, stop: threading.Event) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "In Progress"),
        task("TASK-2", "Ready", dependencies=("TASK-1",)),
        task("TASK-3", "Ready"),
    )

    running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-2", "waiting")])


def test_a_pin_bump_settle_holds_the_dependent_until_the_pin_bump_merge_projects(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Done", references=(CHILD_PR,)),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )
    store.save([pull(10, state="MERGED", repo="acme/starpulse", sha=CHILD)])
    actor = running(board, store, stop, repos=REPOS, settle="pin-bump", pins=Pins())
    assert board.moved() == []

    store.save([pull(11, state="MERGED", sha=PARENT, files=("starpulse",))])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-2", "ready")])


def test_a_review_task_whose_pr_merged_while_the_server_was_down_moves_on_start(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)), task("TASK-2", "Review"))
    store.save([pull(1, state="MERGED")])

    actor = running(board, store, stop)

    assert board.moved() == [("TASK-1", "done")]
    assert actor.derivations["TASK-2"] == 1  # every open task is derived once on start
