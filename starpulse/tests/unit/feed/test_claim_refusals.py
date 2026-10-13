"""A refused agent claim travels `board:claims` of the event log into the feed's claims."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed, follow
from starpulse._internal.feed.claim_refusals import STREAM, ClaimRefusals
from starpulse.tests.machines import MACHINES


def _until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not done():
        assert time.monotonic() < deadline, "the claim never reached the feed"
        time.sleep(0.01)


@pytest.fixture
def stop():
    event = threading.Event()
    yield event
    event.set()


def test_a_board_claims_entry_is_the_tasks_claim_with_its_reason_and_time(
    tmp_path: Path, stop: threading.Event
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    log.append(STREAM, {"task": "TASK-7", "reason": "no worktree", "actor": "agent", "time": "100.5"})
    feed = BoardFeed(None, machines=MACHINES)
    refusals = ClaimRefusals(feed)

    follow(refusals, log, STREAM, refusals.handle_entry, stop=stop, interval=0.01)
    _until(lambda: "TASK-7" in feed.snapshot()["claims"])

    assert feed.snapshot()["claims"] == {"TASK-7": {"reason": "no worktree", "at": 100.5}}


@pytest.mark.parametrize(
    "fields", [{"reason": "r", "time": "1"}, {"task": "TASK-7", "time": "1"}, {"task": "TASK-7", "reason": "r"}]
)
def test_an_entry_missing_its_task_reason_or_time_is_dropped(fields: dict) -> None:
    feed = BoardFeed(None, machines=MACHINES)

    ClaimRefusals(feed).handle_entry("1", fields)

    assert feed.snapshot()["claims"] == {}
