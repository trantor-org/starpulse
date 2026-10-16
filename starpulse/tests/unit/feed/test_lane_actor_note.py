"""A write's actor note outlives a poll of the task that changes no lane: the lane change that follows still names it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from starpulse._internal.board.upstream_backlog import BACKSTOP as BACKSTOP_SCAN_S
from starpulse._internal.board.upstream_backlog import upstream_keys
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.feed.board_feed import BoardFeed
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


def test_a_note_under_the_files_lowercase_id_names_the_actor_of_the_move_placed_under_the_canonical_key(
    tmp_path: Path,
) -> None:
    """An older task file spells its id `task-4613`, so the write notes its writer under that spelling while the feed
    places the move as `TASK-4613`: TASK-4613's six lane entries on 2026-10-16 carried no actor."""
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed(keys=upstream_keys("TASK"), machines=MACHINES)
    feed.record_lanes(HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES), log)
    feed.put(BoardTask(id="TASK-12", team="demo", title="t", lane="ready", observed_at=100.0))
    feed.note_actor("task-12", "agent", "s1", "claude")
    feed.put(BoardTask(id="TASK-12", team="demo", title="t", lane="in_progress", observed_at=110.0))

    entry = [e for e in Tail(log, lane_events.STREAM).poll() if e.fields["lane"] == "in_progress"][0]

    assert (entry.fields.get("actor"), entry.fields.get("session")) == ("agent", "s1")


class _BoardStore:
    """A store holding one saved Board per stream."""

    def __init__(self) -> None:
        self.saved: dict[str, tuple[str, dict]] = {}

    def load_board_state(self, stream: str) -> tuple[str, dict] | None:
        return self.saved.get(stream)

    def save_board_state(self, stream: str, cursor: str, state: dict) -> None:
        self.saved[stream] = (cursor, json.loads(json.dumps(state)))  # a store keeps JSON


def test_a_note_set_before_a_restart_names_its_writer_on_the_first_place_after_it(tmp_path: Path) -> None:
    board, log = _BoardStore(), EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    history = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    before = BoardFeed(machines=MACHINES)
    before.resume(board, "board:tasks", lambda cursor: True)
    before.put(_task("in_progress", "t", 100.0))
    before.seen("7-0")
    before.save()
    before.note_actor("T-1", "agent", "s1", "claude")  # written, not yet placed when the service stops
    before.save()  # the stop's last save

    after = BoardFeed(machines=MACHINES)
    after.record_lanes(history, log)
    after.resume(board, "board:tasks", lambda cursor: True)
    after.put(_task("review", "t", 120.0))  # the first scan after the restart places the write

    entry = [e for e in Tail(log, lane_events.STREAM).poll() if e.fields["lane"] == "review"][0]

    assert (entry.fields.get("actor"), entry.fields.get("session")) == ("agent", "s1")
