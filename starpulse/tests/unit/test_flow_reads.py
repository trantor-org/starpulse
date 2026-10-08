"""Flow health and the level answer from the summaries the history store keeps, and say the same as the row scan."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import event

from starpulse.server import health_response, level_response, trajectories_response
from starpulse.store.history import HistoryStore
from starpulse.tests.integration.test_level_http import LEVEL
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.test_analytics import NOW, ROWS, H

#: The two raw tables a read must never touch: they hold every event and lane change ever kept.
RAW = ("starpulse_machine_events", "starpulse_lane_changes")


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    for i, (task, at, _old, new) in enumerate(ROWS):
        store.record_lane(f"{'a' if task in 'AB' else 'b'}/{i}", task, new, at)
    return store


@pytest.fixture
def statements(store: HistoryStore) -> Iterator[list[str]]:
    seen: list[str] = []

    def capture(_conn, _cursor, statement, *_args) -> None:
        seen.append(statement)

    event.listen(store.engine, "before_cursor_execute", capture)
    yield seen
    event.remove(store.engine, "before_cursor_execute", capture)


def _raw(statements: list[str]) -> list[str]:
    return [s for s in statements if any(table in s for table in RAW)]


def test_flow_health_reads_neither_raw_table(store: HistoryStore, statements: list[str]) -> None:
    body, status = health_response(store, {"hours": ["48"]}, MACHINES, NOW)

    assert (status, _raw(statements)) == (200, [])
    assert statements, "the read went through the captured engine"
    assert json.loads(body)["throughput"]["count"] == 2


class RowScan:
    """The history an adapter supplies: every lane change and trajectory, no summaries, so a read folds them all."""

    def __init__(self, store: HistoryStore) -> None:
        self.lane_path, self.machine_path = store.lane_path, store.machine_path
        self.lane_rows, self.gaps, self.level_runs = store.lane_rows, store.gaps, store.level_runs


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"hours": ["48"]},
        {"hours": ["48"], "stuck_hours": ["1"]},
        {"hours": ["0.5"], "stuck_hours": ["100"]},
        {"hours": ["1000"]},
        {"hours": ["90"], "stuck_hours": ["24"]},
    ],
)
def test_flow_health_from_the_summaries_is_the_bytes_the_row_scan_gives(store: HistoryStore, query: dict) -> None:
    store.record_lane("a/moon", "G", "Moon", 20 * 3600.0)  # a lane the Board machine lacks
    store.record_lane("a/moon2", "G", "Done", 70 * 3600.0)
    store.record_lane("a/moon3", "H", "Moon", 80 * 3600.0)
    store.record_gap("lane", "1-0", "9-0", 4)

    assert health_response(store, query, MACHINES, NOW) == health_response(RowScan(store), query, MACHINES, NOW)


def _add_long_history(store: HistoryStore) -> None:
    """What a level answers with besides `ROWS`: work long finished or stalled before the window, and odd paths."""
    store.record_lane("a/z1", "Z", "In Progress", -3000 * H)
    store.record_lane("a/z2", "Z", "Done", -2900 * H)  # finished more than 12 weeks ago
    store.record_lane("b/y1", "Y", "In Progress", -2500 * H)  # in progress ever since
    store.record_lane("a/m1", "M", "Ready", 60 * H)
    store.record_lane("a/m2", "M", "Moon", 70 * H)  # a lane the Board machine lacks, between two Ready stays
    store.record_lane("a/m3", "M", "Ready", 80 * H)
    store.record_lane("a/m4", "M", "In Progress", 85 * H)
    store.record_lane("b/c1", "A", "Ready", 61 * H)  # the task id of a task source a reported, from source b
    store.record_lane("b/c2", "A", "Done", 97 * H)
    store.record_lane("a/k1", "K", "In Progress", 50 * H)
    store.record_lane("a/k2", "K", "In Progress", 55 * H)  # a reconcile that changes nothing


_WINDOWS = [{}, {"hours": ["48"]}, {"hours": ["0.5"]}, {"hours": ["3050"]}, {"hours": ["2500"]}]


@pytest.mark.parametrize("answer", [level_response, trajectories_response])
@pytest.mark.parametrize("query", _WINDOWS)
def test_the_level_from_the_summaries_is_the_bytes_the_row_scan_gives(store: HistoryStore, answer, query: dict) -> None:
    _add_long_history(store)

    assert answer(store, query, LEVEL, MACHINES, NOW) == answer(RowScan(store), query, LEVEL, MACHINES, NOW)


@pytest.mark.parametrize("answer", [level_response, trajectories_response])
def test_the_level_reads_neither_raw_table(store: HistoryStore, statements: list[str], answer) -> None:
    _add_long_history(store)
    statements.clear()

    body, status = answer(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    assert (status, _raw(statements)) == (200, [])
    assert statements, "the read went through the captured engine"


def test_a_history_with_only_the_row_scan_still_answers_and_that_scan_reads_the_raw_table(
    store: HistoryStore, statements: list[str]
) -> None:
    body, status = level_response(RowScan(store), {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    assert status == 200
    assert _raw(statements), "the control: the capture sees the whole-table read the summaries avoid"
