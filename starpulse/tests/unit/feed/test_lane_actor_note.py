"""A write's actor note outlives a poll of the task that changes no lane: the lane change that follows still names it."""

from __future__ import annotations

from pathlib import Path

import pytest

from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.board.upstream_backlog import BACKSTOP as BACKSTOP_SCAN_S
from starpulse.contracts import BoardTask
from starpulse.tests.machines import MACHINES


def _task(lane: str, title: str, at: float) -> BoardTask:
    return BoardTask(id="T-1", team="demo", title=title, lane=lane, observed_at=at)


@pytest.mark.parametrize(
    ("before", "after"), [("ready", "in_progress"), ("in_progress", "waiting"), ("in_progress", "review")]
)
def test_a_poll_that_changes_no_lane_leaves_the_actor_for_the_move_after_it(
    tmp_path: Path, before: str, after: str
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed(machines=MACHINES)
    feed.record_lanes(HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES), log)
    feed.put(_task(before, "t", 100.0))
    feed.note_actor("T-1", "agent", "s1", "claude")  # the move's write notes its writer before the file lands
    feed.put(_task(before, "t edited", 110.0))  # the watch places the write before it: the same lane
    feed.put(_task(after, "t edited", 120.0))  # the move's own file

    entry = [e for e in Tail(log, lane_events.STREAM).poll() if e.fields["lane"] == after][0]

    assert (entry.fields.get("actor"), entry.fields.get("session")) == ("agent", "s1")


def test_a_lane_change_the_backstop_scan_places_still_names_the_actor_that_wrote_it(tmp_path: Path) -> None:
    """The watch can miss a write, and the board's full scan, 60 s apart, places it: TASK-5016 entered Done 60.18 s
    after its write with no actor."""
    now = [100.0]
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed(machines=MACHINES, clock=lambda: now[0])
    feed.record_lanes(HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES), log)
    feed.put(_task("review", "t", 100.0))
    feed.note_actor("T-1", "starpulse/task-actor")
    now[0] += 2 * BACKSTOP_SCAN_S  # the scan that follows the write by a full interval, run long
    feed.put(_task("done", "t", now[0]))

    entry = [e for e in Tail(log, lane_events.STREAM).poll() if e.fields["lane"] == "done"][0]

    assert entry.fields.get("actor") == "starpulse/task-actor"
