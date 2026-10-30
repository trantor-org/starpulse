"""The task actor moves a Review task whose pull request turned not green: red to its session, pending or draft to a person."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse.board.board_feed import BoardFeed
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.adapter_kit import task

from tests.machines import ROLES
from tests.task_actor_kit import MOVES, PR_ONE, WAITS, Board, pull, running, until

NOT_GREEN_WAITS = {
    **WAITS,
    "review": {"pr_terminal": "MERGED", "pr_red": "SEND_BACK", "pr_pending": "DEMOTE"},
}
NOT_GREEN_MOVES = {
    **MOVES,
    ("review", "SEND_BACK"): "in_progress",
    ("review", "DEMOTE"): "needs_attention",
}
FAILING = {"checks": "failing", "requiredChecks": [{"name": "lint", "result": "failing"}]}


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def _review(store: PullStore, stop: threading.Event, sent_back: list[str]) -> tuple[Board, object]:
    board = Board(BoardFeed(roles=ROLES), task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN") | {"mergeable": "MERGEABLE"}])
    actor = running(board, store, stop, NOT_GREEN_WAITS, NOT_GREEN_MOVES, sent_back=sent_back.append)
    return board, actor


@pytest.mark.parametrize(
    ("red", "reason"),
    [(FAILING, "lint"), ({"mergeable": "CONFLICTING"}, "rebase on origin/main")],
    ids=["failing check", "conflict"],
)
def test_a_review_task_whose_pr_turns_red_returns_to_in_progress_and_its_session_is_told(
    store: PullStore, stop: threading.Event, red: dict, reason: str
) -> None:
    sent_back: list[str] = []
    board, actor = _review(store, stop, sent_back)
    assert not until(lambda: board.moved() != [], within=0.2)

    store.save([pull(1, state="OPEN") | {"mergeable": "MERGEABLE"} | red])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "in_progress")])
    assert until(lambda: sent_back == ["TASK-1"])
    assert reason in str(board.writes[0][2])


def test_a_review_task_whose_checks_are_running_moves_to_needs_attention_with_the_reason(
    store: PullStore, stop: threading.Event
) -> None:
    sent_back: list[str] = []
    board, actor = _review(store, stop, sent_back)

    store.save([pull(1, state="OPEN") | {"checks": "pending"}])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "needs_attention")])
    _, changes, comment, _ = board.writes[0]
    assert "checks still running" in str(comment)
    assert "## Needs attention" in changes["description"]
    assert sent_back == []


def test_a_review_task_whose_pr_was_converted_to_draft_moves_to_needs_attention(
    store: PullStore, stop: threading.Event
) -> None:
    board, actor = _review(store, stop, [])

    store.save([pull(1, state="OPEN") | {"isDraft": True}])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "needs_attention")])


def test_a_review_task_whose_pr_merged_closes_whatever_its_checks_say(
    store: PullStore, stop: threading.Event
) -> None:
    board, actor = _review(store, stop, [])

    store.save([pull(1, state="MERGED") | FAILING])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])


def test_a_review_task_whose_pr_stays_green_stays_in_review(store: PullStore, stop: threading.Event) -> None:
    board, actor = _review(store, stop, [])

    store.save([pull(1, state="OPEN") | {"mergeable": "MERGEABLE", "threads": 2}])
    actor.pulls_changed()

    assert not until(lambda: board.moved() != [], within=0.3)
