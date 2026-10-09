"""One board move is one lane-history row: a status has one spelling, and a second writer of a move adds nothing."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from starpulse.contracts import BoardTask
from starpulse._internal.projections.board_feed import BoardFeed
from starpulse._internal.store.history import HistoryStore
from starpulse.tests.machines import MACHINES

MOVE = ("T-1", 100.0)
REPLAYED = ("trantor/1bdc9eb7-9413-439e-9749-7cd8d7f8bf13", "Waiting")  # a board event: a UUID, a status as spelled
FED = ("trantor/T-1@waiting@100.0", "waiting")  # the lane stream: the lane id, keyed on task, lane and time


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(f"sqlite:///{tmp_path / 'hub.sqlite'}", MACHINES)


@pytest.mark.parametrize("writers", [(REPLAYED, FED), (FED, REPLAYED)], ids=["replay-first", "feed-first"])
def test_a_move_two_writers_record_under_two_spellings_is_one_row_in_the_lane_id(
    store: HistoryStore, writers: tuple[tuple[str, str], tuple[str, str]]
) -> None:
    task, at = MOVE
    store.record_lane("trantor/T-1@in_progress@50.0", task, "In Progress", 50.0)

    written = [store.record_lane(event_id, task, status, at) for event_id, status in writers]

    assert written == [True, False]
    assert store.lane_path(task) == [
        {"at": 50.0, "from": None, "to": "in_progress"},
        {"at": 100.0, "from": "in_progress", "to": "waiting"},
    ]


def test_a_lane_move_read_live_is_dated_by_the_boards_time_not_the_feeds_clock(store: HistoryStore) -> None:
    feed = BoardFeed(machines=MACHINES, clock=lambda: 580.0)  # the feed read the move eight minutes after it was made
    feed.record_lanes(store)

    feed.put(BoardTask(id="T-1", team="demo", title="t", lane="in_progress", observed_at=100.0))

    assert store.lane_path("T-1") == [{"at": 100.0, "from": None, "to": "in_progress"}]


#: One task's hub rows as two writers left them, in the order they landed: the replayed board events (a UUID, a status
#: as spelled, the board's time) and the lane stream (a lane id, the feed's later clock), each chaining off whichever
#: row came before it.
LEGACY = [
    ("trantor/u1", "T-1", None, "Waiting", 100.0),
    ("trantor/T-1@waiting@160.0", "T-1", "Waiting", "waiting", 160.0),  # u1 seen again, a minute late
    ("trantor/u2", "T-1", "waiting", "Ready", 200.0),
    ("trantor/u3", "T-1", "Ready", "In Progress", 300.0),
    ("trantor/T-1@ready@250.0", "T-1", "In Progress", "ready", 250.0),  # u2 seen again, late
    ("trantor/T-1@in_progress@360.0", "T-1", "ready", "in_progress", 360.0),  # u3 seen again, late
    ("trantor/T-1@review@900.0", "T-1", "in_progress", "review", 900.0),  # a move only the stream saw
    ("trantor/u4", "T-1", "review", "Review", 901.0),  # the same move, spelled by the replay
]


def test_a_store_holding_both_writers_rows_ends_with_one_chain_in_the_lane_id(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'hub.sqlite'}"
    held = HistoryStore(url, MACHINES)
    with held.engine.begin() as db:
        for event_id, task, old, new, at in LEGACY:
            db.execute(
                text(
                    "INSERT INTO starpulse_lane_changes (event_id, task, old_status, new_status, observed_at) "
                    "VALUES (:e, :t, :o, :n, :a)"
                ),
                {"e": event_id, "t": task, "o": old, "n": new, "a": at},
            )
    held.rebuild_summaries()
    held.engine.dispose()

    repaired = HistoryStore(url, MACHINES)

    assert repaired.lane_path("T-1") == [
        {"at": 100.0, "from": None, "to": "waiting"},
        {"at": 200.0, "from": "waiting", "to": "ready"},
        {"at": 300.0, "from": "ready", "to": "in_progress"},
        {"at": 900.0, "from": "in_progress", "to": "review"},
    ]
    assert repaired.summary_differences() == []
    assert HistoryStore(url, MACHINES).lane_changes() == repaired.lane_changes()  # a second start repairs nothing
