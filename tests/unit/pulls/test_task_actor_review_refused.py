"""A Review move the board refuses on a ready PR hands its holder the refusal through `delivered`, once."""

import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.event_log.wake import StopEvent
from starpulse.pulls.adapters.inbound import task_actor
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.adapter_kit import task

from tests.task_actor_kit import PR_ONE, Board, pull, running, until

REASON = "Review needs PRs with no open thread and no conflict"


@pytest.fixture
def store(tmp_path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = StopEvent()
    yield event
    event.set()


def in_progress() -> Board:
    return Board(BoardFeed(), task("TASK-1", "In Progress", references=(PR_ONE,)))


def test_a_review_move_the_board_refuses_wakes_the_holder_with_the_reason_once(
    store: PullStore, stop: threading.Event
) -> None:
    board = in_progress()
    board.refusing["review"] = REASON
    told: list[tuple[str, str]] = []
    store.save([pull(1, state="OPEN")])

    actor = running(board, store, stop, delivered=lambda name, verdict: told.append((name, verdict)))
    actor.pulls_changed()

    assert until(lambda: told == [("TASK-1", f"Review refused: {REASON}")])
    assert not until(lambda: len(told) > 1, within=0.2)


def test_a_review_move_the_board_accepts_wakes_no_one(store: PullStore, stop: threading.Event) -> None:
    board = in_progress()
    told: list[tuple[str, str]] = []
    store.save([pull(1, state="OPEN")])

    running(board, store, stop, delivered=lambda name, verdict: told.append((name, verdict)))

    assert until(lambda: board.moved() == [("TASK-1", "review")])
    assert told == []


def test_a_review_move_that_fails_transiently_wakes_no_one(
    store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task_actor, "LOCK_BACKOFF_S", ())
    board = in_progress()

    def locked(*_: object, **__: object) -> Written:
        raise OSError("database is locked")

    board.edit = locked  # type: ignore[method-assign]
    told: list[tuple[str, str]] = []
    store.save([pull(1, state="OPEN")])

    running(board, store, stop, delivered=lambda name, verdict: told.append((name, verdict)))

    assert not until(lambda: bool(told), within=0.2)
