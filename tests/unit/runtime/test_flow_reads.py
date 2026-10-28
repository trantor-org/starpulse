"""Flow health and the level answer from the summaries the history store keeps, and say the same as the row scan."""

import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from starpulse.flow_metrics.adapters.outbound import history
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.flow_metrics.model.level import Level, Orbit, Terminal
from starpulse.runtime import server
from starpulse.runtime.server import health_response, trajectories_response

from tests.machines import MACHINES
from tests.rows import rows_fetched
from tests.summaries import assert_matches_rebuild
from tests.unit.flow_metrics.test_analytics import NOW, ROWS, H

LEVEL = Level(
    "board",
    "done",
    (Terminal("done", "goal"),),
    gates=("review",),
    orbit=Orbit("working", ("in_progress", "review")),
)

#: The two raw tables a read must never touch: they hold every event and lane change ever kept.
RAW = ("starpulse_machine_events", "starpulse_lane_changes")


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    engine = create_engine(url)
    store = HistoryStore(url, MACHINES, engine)
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
        self.lane_path, self.machine_path, self.task_events = store.lane_path, store.machine_path, store.task_events
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


def _record_all(store: HistoryStore, changes: list[tuple[str, str, str, float]]) -> None:
    """The lane changes `(event id, task, lane, at)` `record_lane` would write one by one, in a single transaction."""
    with store.engine.begin() as db:
        for event_id, task, lane, at in changes:
            store._fold_lane(db, event_id, task, lane, at)


def _churn(store: HistoryStore, tasks: int) -> None:
    """`tasks` more tasks that each pass through every lane inside the default week, ending in Done."""
    _record_all(
        store,
        [
            (f"a/churn-{task}-{step}", f"churn-{task}", lane, (50 + step + task % 40 / 10) * H)
            for task in range(tasks)
            for step, lane in enumerate(("To Do", "Ready", "In Progress", "Review", "Done"))
        ],
    )


def _health_rows(store: HistoryStore) -> int:
    """The rows one health read fetches, after a read that lets the engine open its connection."""
    health_response(store, {}, MACHINES, NOW)
    with rows_fetched(store.engine) as fetched:
        body, status = health_response(store, {}, MACHINES, NOW)
    assert status == 200, body
    return fetched[0]


def test_flow_health_fetches_no_more_rows_as_the_week_holds_more_lane_intervals(store: HistoryStore) -> None:
    few = _health_rows(store)
    _churn(store, 40)

    assert _health_rows(store) == few
    assert_matches_rebuild(store)


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
    _record_all(store, [(f"a/flight-{task}", f"flight-{task}", "In Progress", NOW - H / 2) for task in range(200)])

    assert _health_rows(store) == few
    assert_matches_rebuild(store)


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


@pytest.mark.parametrize("query", _WINDOWS)
def test_the_level_from_the_summaries_is_the_bytes_the_row_scan_gives(store: HistoryStore, query: dict) -> None:
    _add_long_history(store)

    assert trajectories_response(store, query, LEVEL, MACHINES, NOW) == trajectories_response(
        RowScan(store), query, LEVEL, MACHINES, NOW
    )


def test_the_level_reads_neither_raw_table(store: HistoryStore, statements: list[str]) -> None:
    _add_long_history(store)
    statements.clear()

    body, status = trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    assert (status, _raw(statements)) == (200, [])
    assert statements, "the read went through the captured engine"


def test_a_history_with_only_the_row_scan_still_answers_and_that_scan_reads_the_raw_table(
    store: HistoryStore, statements: list[str]
) -> None:
    body, status = trajectories_response(RowScan(store), {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    assert status == 200
    assert _raw(statements), "the control: the capture sees the whole-table read the summaries avoid"


def test_a_level_window_read_in_one_task_chunks_groups_the_same_runs(store: HistoryStore, monkeypatch) -> None:
    _add_long_history(store)
    window = {"now": NOW, "window_s": 48 * H}
    whole = store.level_window(LEVEL, **window)
    monkeypatch.setattr(history, "_TASKS_PER_QUERY", 1)

    chunked = _fresh(store).level_window(LEVEL, **window)

    assert len(whole.runs) > 1
    assert sorted(chunked.runs, key=_run_key) == sorted(whole.runs, key=_run_key)


def _run_key(run) -> tuple[str, str]:
    return run.source, run.task


def _fresh(store: HistoryStore) -> HistoryStore:
    """A store over the same database with no level window cached yet."""
    return HistoryStore(str(store.engine.url), MACHINES, store.engine)


def test_level_window_groups_runs_by_the_stored_source_without_resolving_one_per_row(
    store: HistoryStore, monkeypatch
) -> None:
    _add_long_history(store)
    window = {"now": NOW, "window_s": 48 * H}
    expected = sorted(store.level_window(LEVEL, **window).runs, key=_run_key)

    def refuse(event_id: str) -> str:
        raise AssertionError(f"resolved the source of {event_id} per row")

    monkeypatch.setattr(history, "source", refuse)

    assert sorted(_fresh(store).level_window(LEVEL, **window).runs, key=_run_key) == expected
    with store.engine.begin() as db:
        db.execute(text("UPDATE starpulse_lane_intervals SET source = 'moved' WHERE event_id IN ('b/c1', 'b/c2')"))
    assert {(run.source, run.task) for run in _fresh(store).level_window(LEVEL, **window).runs} >= {("moved", "A")}


def test_level_window_has_sql_order_the_task_index_by_entered_at_without_a_sort(store: HistoryStore) -> None:
    executions: list[tuple[str, tuple]] = []

    def capture(_conn, _cursor, statement, parameters, *_args) -> None:
        if "FROM starpulse_lane_intervals" in statement and "IN (" in statement:
            executions.append((statement, parameters))

    event.listen(store.engine, "before_cursor_execute", capture)
    try:
        store.level_window(LEVEL, now=NOW, window_s=48 * H)
    finally:
        event.remove(store.engine, "before_cursor_execute", capture)

    assert executions, "the read fetched the stays of the tasks it needs"
    statement, parameters = executions[0]
    with store.engine.connect() as db:
        plan = " ".join(row[3] for row in db.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement}", parameters))

    assert "ORDER BY" in statement
    assert "USING INDEX ix_starpulse_lane_intervals_task_entered" in plan
    assert "TEMP B-TREE" not in plan


def _interval_reads(statements: list[str]) -> list[str]:
    return [s for s in statements if "FROM starpulse_lane_intervals" in s]


def _window(store: HistoryStore, now: float = NOW):
    return store.level_window(LEVEL, now=now, window_s=48 * H)


def test_a_second_level_window_with_no_summary_write_between_reads_nothing(
    store: HistoryStore, statements: list[str]
) -> None:
    first = _window(store)
    statements.clear()

    again = _window(store, NOW + 30)

    assert (again, _interval_reads(statements)) == (first, [])


@pytest.mark.parametrize(
    "write",
    [
        lambda store: store.record_lane("a/new", "N", "In Progress", NOW - H),
        lambda store: store.record_machine("1-0", {"machine": "board", "event": "start", "task": "N", "time": NOW - H}),
        lambda store: store.rebuild_summaries(),
    ],
    ids=["record_lane", "record_machine", "rebuild_summaries"],
)
def test_a_summary_write_between_two_level_windows_forces_a_fresh_read(
    store: HistoryStore, statements: list[str], write
) -> None:
    _window(store)
    write(store)
    statements.clear()

    _window(store)

    assert _interval_reads(statements)


def test_the_level_a_cached_window_answers_is_the_bytes_a_fresh_store_gives(store: HistoryStore) -> None:
    trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    cached = trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW + 30)

    fresh = HistoryStore(str(store.engine.url), MACHINES)
    assert cached == trajectories_response(fresh, {"hours": ["48"]}, LEVEL, MACHINES, NOW + 30)


def test_a_reader_never_sees_a_window_older_than_the_last_write_that_completed(store: HistoryStore) -> None:
    written, stop, stale = [0], threading.Event(), []

    def write() -> None:
        for i in range(1, 41):
            store.record_lane(f"a/w-{i}", f"w-{i}", "In Progress", NOW - H)
            written[0] = i
        stop.set()

    def read() -> None:
        while not stop.is_set():
            done = written[0]
            tasks = sum(run.task.startswith("w-") for run in _window(store).runs)
            if tasks < done:
                stale.append((done, tasks))

    readers = [threading.Thread(target=read) for _ in range(4)]
    for reader in readers:
        reader.start()
    write()
    for reader in readers:
        reader.join()

    assert stale == []


@pytest.fixture
def computed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The views the level routes computed rather than answered from the memo, in order."""
    seen: list[str] = []
    for name in ("trajectory_analytics",):
        monkeypatch.setattr(server, name, _counting(seen, name, getattr(server, name)))
    return seen


def _counting(seen: list[str], name: str, view):
    def counted(*args, **kwargs):
        seen.append(name)
        return view(*args, **kwargs)

    return counted


def test_a_repeat_request_with_no_summary_write_between_is_answered_from_the_memo(
    store: HistoryStore, computed: list[str]
) -> None:
    first = trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    again = trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW + 1)

    assert (again, computed) == (first, ["trajectory_analytics"])


def test_a_summary_write_forgets_the_memo(store: HistoryStore, computed: list[str]) -> None:
    trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)
    store.record_lane("a/new", "N", "In Progress", NOW - H)

    trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    assert computed == ["trajectory_analytics", "trajectory_analytics"]


def test_a_request_in_a_later_second_bucket_computes_again(store: HistoryStore, computed: list[str]) -> None:
    trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW + history._ANSWER_BUCKET_S)

    assert computed == ["trajectory_analytics", "trajectory_analytics"]


def test_distinct_query_params_get_distinct_entries(store: HistoryStore, computed: list[str]) -> None:
    day = trajectories_response(store, {"hours": ["24"]}, LEVEL, MACHINES, NOW)
    two_days = trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    assert day != two_days
    assert trajectories_response(store, {"hours": ["24"]}, LEVEL, MACHINES, NOW) == day
    assert computed == ["trajectory_analytics", "trajectory_analytics"]


def test_params_a_route_does_not_read_share_its_entry(store: HistoryStore, computed: list[str]) -> None:
    trajectories_response(store, {"hours": ["48"]}, LEVEL, MACHINES, NOW)

    trajectories_response(store, {"hours": ["48"], "cachebuster": ["1"]}, LEVEL, MACHINES, NOW)

    assert computed == ["trajectory_analytics"]


def test_the_memo_holds_at_most_its_bound_and_forgets_the_least_recently_used(
    store: HistoryStore, computed: list[str]
) -> None:
    kept = history._ANSWERS_KEPT
    for hours in range(1, kept + 2):
        trajectories_response(store, {"hours": [str(hours)]}, LEVEL, MACHINES, NOW)
    computed.clear()

    trajectories_response(store, {"hours": [str(kept + 1)]}, LEVEL, MACHINES, NOW)
    assert computed == []
    trajectories_response(store, {"hours": ["1"]}, LEVEL, MACHINES, NOW)

    assert computed == ["trajectory_analytics"]
