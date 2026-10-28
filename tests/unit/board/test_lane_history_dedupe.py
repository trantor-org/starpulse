"""One board move is one lane-history row: a status has one spelling, and a second writer of a move adds nothing."""

from __future__ import annotations

from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.contracts import BoardTask
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore

from tests.machines import MACHINES, ROLES

MOVE = ("T-1", 100.0)
REPLAYED = ("trantor/1bdc9eb7-9413-439e-9749-7cd8d7f8bf13", "Waiting")  # a board event: a UUID, a status as spelled
FED = ("trantor/T-1@waiting@100.0", "waiting")  # the lane stream: the lane id, keyed on task, lane and time


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)


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
    feed = BoardFeed(
        roles=ROLES, machines=MACHINES, clock=lambda: 580.0
    )  # the feed read the move eight minutes after it was made
    feed.record_lanes(store)

    feed.put(BoardTask(id="T-1", team="demo", title="t", lane="in_progress", observed_at=100.0))

    assert store.lane_path("T-1") == [{"at": 100.0, "from": None, "to": "in_progress"}]
