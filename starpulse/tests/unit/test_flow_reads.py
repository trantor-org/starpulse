"""Flow health and the level answer from the summaries the history store keeps, and say the same as the row scan."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import event

from starpulse._internal.api.server import health_response, level_response, trajectories_response
from starpulse._internal.store.history import HistoryStore
from starpulse.tests.integration.test_level_http import LEVEL
from starpulse.tests.machines import MACHINES
from starpulse.tests.rows import rows_fetched
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


def _churn(store: HistoryStore, tasks: int) -> None:
    """`tasks` more tasks that each pass through every lane inside the default week, ending in Done."""
    for task in range(tasks):
        for step, lane in enumerate(("To Do", "Ready", "In Progress", "Review", "Done")):
            store.record_lane(f"a/churn-{task}-{step}", f"churn-{task}", lane, (50 + step + task % 40 / 10) * H)


def _health_rows(store: HistoryStore) -> int:
    """The rows one health read fetches, after a read that lets the engine open its connection."""
    health_response(store, {}, MACHINES, NOW)
    with rows_fetched(store.engine) as fetched:
        body, status = health_response(store, {}, MACHINES, NOW)
    assert status == 200, body
    return fetched[0]


def test_flow_health_fetches_no_more_rows_as_the_week_holds_more_lane_intervals(store: HistoryStore) -> None:
    few = _health_rows(store)
    _churn(store, 200)

    assert (_health_rows(store), store.summary_differences()) == (few, [])


def test_flow_health_seeks_entries_by_the_window_not_every_stay(store: HistoryStore) -> None:
    executions: list[tuple[str, tuple]] = []

    def capture(_conn, _cursor, statement, parameters, *_args) -> None:
        if "entered_at BETWEEN" in statement:
            executions.append((statement, parameters))

    event.listen(store.engine, "before_cursor_execute", capture)
    try:
        health_response(store, {}, MACHINES, NOW)
    finally:
        event.remove(store.engine, "before_cursor_execute", capture)

    assert len(executions) == 1
    statement, parameters = executions[0]
    with store.engine.connect() as db:
        plan = " ".join(row[3] for row in db.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement}", parameters))

    assert "ix_starpulse_lane_intervals_entered" in plan


def test_flow_health_fetches_no_row_for_a_task_in_flight_that_is_not_stuck(store: HistoryStore) -> None:
    few = _health_rows(store)
    for task in range(200):
        store.record_lane(f"a/flight-{task}", f"flight-{task}", "In Progress", NOW - H / 2)

    assert (_health_rows(store), store.summary_differences()) == (few, [])


def test_flow_health_counts_the_tasks_in_flight_and_lists_the_stuck_ones(store: HistoryStore) -> None:
    for task in range(5):
        store.record_lane(f"a/flight-{task}", f"flight-{task}", "In Progress", NOW - H / 2)
        store.record_lane(f"a/stuck-{task}", f"stuck-{task}", "In Progress", NOW - (30 + task) * H)

    body, status = health_response(store, {"hours": ["48"]}, MACHINES, NOW)
    health = json.loads(body)
    working = next(s for s in health["states"] if s["id"] == "in_progress")
    stuck = [entry["task"] for entry in health["stuck"] if entry["task"].startswith(("flight", "stuck"))]

    assert (status, stuck) == (200, [f"stuck-{task}" for task in (4, 3, 2, 1, 0)])
    assert working["open"] >= 10


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
