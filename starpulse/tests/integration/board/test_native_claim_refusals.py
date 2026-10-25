"""A claim the native board writer refuses lands on `board:claims` in the event log, where the claim-refusal view reads it."""

from pathlib import Path
from typing import Any

import pytest

from starpulse.board.model.seam import Board
from starpulse.board.board_feed import BoardFeed
from starpulse.board.claim_refusals import CLAIMS_STREAM, ClaimRefusals
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.tests.unit.board.test_native_rules import DONE_NEEDS_PR, ruled

CLAIM_NEEDS_PR: dict[str, Any] = {
    "on": {"to": "In Progress"},
    "require": {"field": {"field": "references", "matches": r"/pull/\d+$", "min": 1}},
    "reason": "In Progress needs a pull request in references",
}


def attached(base: Path) -> tuple[Board, EventLog]:
    """A native board holding `task-1` To Do whose rules refuse any claim and any move to Done, attached to an empty
    event log."""
    _, built = ruled(base, [CLAIM_NEEDS_PR, DONE_NEEDS_PR], status="To Do")
    log = EventLog(f"sqlite:///{base / 'events.sqlite'}")
    assert built.attach is not None
    built.attach(log)
    return built, log


def test_a_refused_claim_is_appended_to_board_claims_with_its_task_actor_reason_and_time(tmp_path: Path) -> None:
    built, log = attached(tmp_path)
    assert built.writer is not None

    written = built.writer("task-1", "In Progress", "agent", "session-1")

    [row] = Tail.replay(log, CLAIMS_STREAM).poll()
    assert not written.ok
    assert (row.fields["task"], row.fields["actor"], row.fields["reason"]) == ("task-1", "agent", written.output)
    assert float(row.fields["time"]) > 0


@pytest.mark.parametrize(("status", "actor", "session"), [("Done", "agent", "session-1"), ("In Progress", "operator", "")])
def test_a_refused_write_that_is_not_an_agent_claim_appends_no_claim_refusal(
    tmp_path: Path, status: str, actor: str, session: str
) -> None:
    built, log = attached(tmp_path)
    assert built.writer is not None

    built.writer("task-1", status, actor, session)

    assert Tail.replay(log, CLAIMS_STREAM).poll() == []


def test_the_claim_refusal_view_shows_the_writers_refusal_read_from_the_log_alone(tmp_path: Path) -> None:
    built, log = attached(tmp_path)
    assert built.writer is not None
    feed = BoardFeed()
    view = ClaimRefusals(feed)

    built.writer("task-1", "In Progress", "agent", "session-1")
    for row in Tail.replay(log, CLAIMS_STREAM).poll():  # the event log is the only source: no Redis, no bridge
        view.handle_entry(str(row.id), row.fields)

    [(task, shown)] = feed.snapshot()["claims"].items()
    assert task.lower() == "task-1"
    assert shown["reason"] == CLAIM_NEEDS_PR["reason"]
