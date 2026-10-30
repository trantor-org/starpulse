"""A board write records the lane it moved a task to with the request's actor when it is written; the watch that places
the change later finds it recorded."""

from __future__ import annotations

from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.contracts import BoardTask
from starpulse.event_log import lane_events
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.application.commands.guard import Who, record_written

from tests.machines import MACHINES, ROLES


def _task(lane: str, at: float) -> BoardTask:
    return BoardTask(id="T-1", team="demo", title="t", lane=lane, observed_at=at)


def _site(tmp_path: Path) -> tuple[BoardFeed, HistoryStore, EventLog]:
    url = f"sqlite:///{tmp_path / 'events.sqlite'}"
    log, store, feed = EventLog(url), HistoryStore(url, MACHINES), BoardFeed(roles=ROLES, machines=MACHINES)
    feed.record_lanes(store, log)
    return feed, store, log


def test_a_write_then_its_placement_gives_one_history_row_and_one_entry_with_the_requests_actor(tmp_path: Path) -> None:
    feed, store, log = _site(tmp_path)
    feed.put(_task("ready", 100.0))

    written = record_written(
        feed,
        "T-1",
        Who("agent", "s1", "claude"),
        lambda: Written(True, "Updated task T-1", lane="in_progress", at=110.0),
    )
    feed.put(_task("in_progress", 120.0))  # the watch places the write

    entries = [e for e in Tail.replay(log, lane_events.STREAM).poll() if e.fields["lane"] == "in_progress"]
    assert written.ok
    assert len(entries) == 1
    assert [step["to"] for step in store.lane_path("T-1")] == ["ready", "in_progress"]
    assert [(e.fields.get("actor"), e.fields.get("session"), e.fields.get("harness")) for e in entries] == [
        ("agent", "s1", "claude")
    ]


def test_a_write_that_moves_no_lane_records_nothing_and_the_placement_is_external(tmp_path: Path) -> None:
    feed, store, log = _site(tmp_path)
    feed.put(_task("ready", 100.0))

    record_written(feed, "T-1", Who("agent", "s1", "claude"), lambda: Written(True, "Updated task T-1"))
    feed.put(_task("in_progress", 120.0))

    entry = [e for e in Tail.replay(log, lane_events.STREAM).poll() if e.fields["lane"] == "in_progress"][0]
    assert [step["to"] for step in store.lane_path("T-1")] == ["ready", "in_progress"]
    assert entry.fields.get("actor") == lane_events.EXTERNAL_ACTOR


def test_a_refused_write_records_nothing(tmp_path: Path) -> None:
    feed, store, _ = _site(tmp_path)
    feed.put(_task("ready", 100.0))

    refused = Written(False, "refused", lane="in_progress", at=110.0)
    record_written(feed, "T-1", Who("agent", "s1", "claude"), lambda: refused)

    assert [step["to"] for step in store.lane_path("T-1")] == ["ready"]
