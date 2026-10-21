"""A refused agent claim travels `board:claims` of the event log into the feed's claims."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed, follow
from starpulse._internal.feed.claim_refusals import CLAIMS_STREAM, ClaimRefusals
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
    log._append(CLAIMS_STREAM, {"task": "TASK-7", "reason": "no worktree", "actor": "agent", "time": "100.5"})
    feed = BoardFeed(None, machines=MACHINES)
    refusals = ClaimRefusals(feed)

    follow(refusals, log, CLAIMS_STREAM, refusals.handle_entry, stop=stop, interval=0.01)
    _until(lambda: "TASK-7" in feed.snapshot()["claims"])

    assert feed.snapshot()["claims"] == {"TASK-7": {"reason": "no worktree", "at": 100.5}}


@pytest.mark.parametrize(
    "fields", [{"reason": "r", "time": "1"}, {"task": "TASK-7", "time": "1"}, {"task": "TASK-7", "reason": "r"}]
)
def test_an_entry_missing_its_task_reason_or_time_is_dropped(fields: dict) -> None:
    feed = BoardFeed(None, machines=MACHINES)

    ClaimRefusals(feed).handle_entry("1", fields)

    assert feed.snapshot()["claims"] == {}


def _claim(entry_id: str, task: str) -> tuple[str, dict]:
    return entry_id, {"task": task, "reason": "no worktree", "time": "100.5"}


def test_a_subscriber_connected_through_the_replay_gets_one_snapshot_not_a_claim_per_replayed_entry() -> None:
    feed = BoardFeed(None, machines=MACHINES)
    refusals = ClaimRefusals(feed)
    entries = [_claim(f"{n}-0", f"TASK-{n}") for n in range(1, 4)]
    _, changes = feed.subscribe()

    refusals.expect(entries[-1][0])
    for entry in entries:
        refusals.handle_entry(*entry)
    kinds = []
    while not changes.empty():
        kinds.append(changes.get_nowait()[0])
    refusals.handle_entry(*_claim("4-0", "TASK-4"))

    assert kinds == ["snapshot"]
    assert sorted(feed.snapshot()["claims"]) == ["TASK-1", "TASK-2", "TASK-3", "TASK-4"]
    assert changes.get_nowait()[0] == "claim"  # once the replay is read, a new entry is a live change
