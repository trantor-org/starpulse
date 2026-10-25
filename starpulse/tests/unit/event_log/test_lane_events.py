"""The lane stream's edges: what two sources may share, and when the feed appends."""

from __future__ import annotations

import threading
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.contracts import BoardTask
from starpulse.event_log import lane_events
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.flow_metrics.history import HistoryStore
from starpulse.tests.machines import MACHINES, ROLES

GOOD = {"task": "T-1", "lane": "in_progress", "time": 5.0}


def test_two_sources_that_key_a_task_alike_each_keep_their_own_lane_history(tmp_path: Path) -> None:
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)

    assert store.record_lane_entry("ana/T-1@in_progress@5.0", GOOD) is True
    assert store.record_lane_entry("bob/T-1@in_progress@6.0", {**GOOD, "time": 6.0}) is True  # not ana's repeat
    assert store.record_lane_entry("ana/T-1@in_progress@7.0", {**GOOD, "time": 7.0}) is False  # ana's own repeat

    assert sorted(event_id for event_id, *_ in store.lane_changes()) == [
        "ana/T-1@in_progress@5.0",
        "bob/T-1@in_progress@6.0",
    ]


def test_a_lane_entry_is_appended_only_when_the_history_wrote_a_row(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'ic.sqlite'}")
    store = HistoryStore(f"sqlite:///{tmp_path / 'ic.sqlite'}", MACHINES)
    clock = iter(range(100, 200))
    feed = BoardFeed(roles=ROLES, machines=MACHINES, clock=lambda: float(next(clock)))
    feed.record_lanes(store, log)
    store.record_lane("T-1@in_progress@50.0", "T-1", "in_progress", 50.0)  # the history already has this lane

    feed.put(BoardTask(id="T-1", team="demo", title="t", lane="in_progress"))
    feed.put(BoardTask(id="T-2", team="demo", title="t", lane="review", labels=("kind-execute",), milestone="m-1"))

    [entry] = Tail.replay(log, lane_events.STREAM).poll()
    assert entry.event_id.startswith("T-2@review@")
    assert entry.fields["labels"] == ["kind-execute"] and entry.fields["milestone"] == "m-1"
    assert "title" not in entry.fields


def test_every_lane_entry_appended_from_now_on_without_an_actor_is_counted(tmp_path: Path) -> None:
    """The counter reads the stream, so a move any writer leaves unnamed counts: the live `put`, the reconcile."""
    log = EventLog(f"sqlite:///{tmp_path / 'ic.sqlite'}")
    task = BoardTask(id="T-1", team="demo", title="t", lane="ready")
    lane_events.append(log, "T-0@ready@1.0", "T-0", "ready", 1.0)  # before the count began
    stop = threading.Event()
    unattributed = lane_events.Unattributed()
    unattributed.follow(log, stop)

    log._append(lane_events.STREAM, lane_events.entry(task, 2.0), event_id="T-1@ready@2.0")
    log._append(lane_events.STREAM, lane_events.entry(task, 3.0, "starpulse/task-actor"), event_id="T-1@done@3.0")
    lane_events.append(log, "T-2@review@4.0", "T-2", "review", 4.0)
    log._append("pulls:notes", {"task": "T-3", "actor": None})  # another stream

    done = threading.Event()
    while unattributed.count() < 2 and not done.wait(0.05):
        pass
    stop.set()
    assert unattributed.count() == 2
    assert "starpulse_board_lane_unattributed_total 2\n" in unattributed.exposition()


def test_a_lane_entry_names_the_profile_under_profile_and_keeps_no_legacy_assignee() -> None:
    task = BoardTask(id="T-1", team="demo", title="t", lane="ready", profile="@agent-standard-high", assignee="s-1")

    fields = lane_events.entry(task, 2.0)

    assert (fields["profile"], "assignee" in fields) == ("@agent-standard-high", False)
