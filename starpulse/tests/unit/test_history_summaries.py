"""The history store keeps step, case and lane-interval summaries as it records, so a read need not fold every row."""

from pathlib import Path

import pytest
from sqlalchemy import text

from starpulse.history import HistoryStore
from starpulse.tests.machines import MACHINES

#: 2026-09-22 00:00 UTC, so an event a few seconds before it falls on the day before.
MIDNIGHT = 1790035200.0
_TASK = {"machine": "in-progress", "task": "PROJ-7"}


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    return HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)


def _rows(store: HistoryStore, table: str, columns: str) -> list[tuple]:
    with store.engine.connect() as db:
        return [tuple(r) for r in db.execute(text(f"SELECT {columns} FROM {table} ORDER BY {columns}"))]


def _steps(store: HistoryStore) -> list[tuple]:
    return _rows(store, "starpulse_step_summaries", "day, machine, from_state, to_state, steps, duration_s")


def _cases(store: HistoryStore) -> list[tuple]:
    return _rows(
        store,
        "starpulse_cases",
        "machine, source, kind, case_id, state, since, first_at, last_event_id, last_at",
    )


def _intervals(store: HistoryStore) -> list[tuple]:
    return _rows(store, "starpulse_lane_intervals", "task, lane, entered_at, left_at, event_id")


def _event(store: HistoryStore, event_id: str, event: str, at: float, **fields) -> None:
    store.record_machine(event_id, {"event_id": event_id, "event": event, "time": str(at)} | (_TASK | fields))


def test_a_machine_event_counts_its_step_on_its_utc_day_and_moves_its_case(store: HistoryStore) -> None:
    _event(store, "e1", "WORKTREE_READY", MIDNIGHT - 10)
    _event(store, "e2", "RED_PROVEN", MIDNIGHT + 30)
    _event(store, "e3", "GREEN", MIDNIGHT + 100)
    _event(store, "e4", "GREEN", MIDNIGHT + 130)  # a loop: the task stays in green

    assert _steps(store) == [
        ("2026-09-21", "in-progress", "", "worktree_ready", 1, 0.0),
        ("2026-09-22", "in-progress", "green", "green", 1, 30.0),
        ("2026-09-22", "in-progress", "red_proven", "green", 1, 70.0),
        ("2026-09-22", "in-progress", "worktree_ready", "red_proven", 1, 40.0),
    ]
    assert _cases(store) == [
        (
            "in-progress",
            "unattributed",
            "task",
            "PROJ-7",
            "green",
            MIDNIGHT + 100,
            MIDNIGHT - 10,
            "e4",
            MIDNIGHT + 130,
        )
    ]


def test_a_redelivered_event_changes_no_summary(store: HistoryStore) -> None:
    _event(store, "e1", "WORKTREE_READY", 100.0)
    _event(store, "e2", "RED_PROVEN", 130.0)
    before = (_steps(store), _cases(store))

    _event(store, "e2", "RED_PROVEN", 130.0)

    assert (_steps(store), _cases(store)) == before


def test_a_run_keyed_event_moves_its_own_case_and_a_forwarded_source_keeps_its_own(store: HistoryStore) -> None:
    run = {"machine": "authoring-skills", "run": "run-1", "task": None}
    store.record_machine("r1", {"event_id": "r1", "event": "GUIDANCE_READ", "time": "5"} | run)
    _event(store, "pod-a/e1", "WORKTREE_READY", 10.0)
    _event(store, "e1", "WORKTREE_READY", 11.0)

    assert [row[:5] for row in _cases(store)] == [
        ("authoring-skills", "unattributed", "run", "run-1", "guidance_read"),
        ("in-progress", "pod-a", "task", "PROJ-7", "worktree_ready"),
        ("in-progress", "unattributed", "task", "PROJ-7", "worktree_ready"),
    ]


def test_an_event_of_an_undrawn_machine_or_without_a_case_is_not_summarised(store: HistoryStore) -> None:
    _event(store, "e1", "WORKTREE_READY", 10.0, machine="not-drawn")
    _event(store, "e2", "WORKTREE_READY", 11.0, task=None)

    assert (_steps(store), _cases(store)) == ([], [])


def test_the_summary_is_written_in_the_transaction_of_the_event_and_its_cursor(
    store: HistoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args) -> None:
        raise RuntimeError("the cursor write failed")

    monkeypatch.setattr(store, "_save_cursor", fail)
    with pytest.raises(RuntimeError):
        store.record_machine("1-0", {"event_id": "e1", "event": "WORKTREE_READY", "time": "10"} | _TASK, cursor=1)

    assert (_steps(store), _cases(store), _rows(store, "starpulse_machine_events", "event_id")) == ([], [], [])


def test_a_lane_change_closes_the_open_interval_and_opens_the_next(store: HistoryStore) -> None:
    store.record_lane("T-1@Ready@10", "T-1", "Ready", 10.0)
    store.record_lane("T-1@In Progress@25", "T-1", "In Progress", 25.0)
    store.record_lane("T-1@In Progress@30", "T-1", "In Progress", 30.0)  # a reconcile: no change
    store.record_lane("T-1@In Progress@25", "T-1", "In Progress", 25.0)  # the same change replayed

    assert _intervals(store) == [
        ("T-1", "In Progress", 25.0, None, "T-1@In Progress@25"),
        ("T-1", "Ready", 10.0, 25.0, "T-1@Ready@10"),
    ]


def test_a_lane_change_is_a_step_of_the_board_machine_and_moves_the_tasks_case(store: HistoryStore) -> None:
    store.record_lane("T-1@Ready@10", "T-1", "Ready", MIDNIGHT + 10)
    store.record_lane("T-1@In Progress@25", "T-1", "In Progress", MIDNIGHT + 25)
    store.record_lane("T-1@Moon@40", "T-1", "Moon", MIDNIGHT + 40)  # a lane the Board machine lacks

    assert _steps(store) == [
        ("2026-09-22", "board", "", "ready", 1, 0.0),
        ("2026-09-22", "board", "ready", "in_progress", 1, 15.0),
    ]
    assert [(row[0], row[3], row[4], row[7]) for row in _cases(store)] == [
        ("board", "T-1", "in_progress", "T-1@In Progress@25")
    ]
    assert [row[1] for row in _intervals(store)] == ["In Progress", "Moon", "Ready"], "health still counts every lane"


def _fill(store: HistoryStore) -> None:
    _event(store, "e1", "WORKTREE_READY", MIDNIGHT - 10)
    _event(store, "e2", "RED_PROVEN", MIDNIGHT + 30)
    _event(store, "e3", "GREEN", MIDNIGHT + 100, task="PROJ-8")
    store.record_machine(
        "r1",
        {"event_id": "r1", "event": "GUIDANCE_READ", "time": "5", "run": "run-1"} | {"machine": "authoring-skills"},
    )
    store.record_lane("T-1@Ready@10", "T-1", "Ready", MIDNIGHT + 10)
    store.record_lane("T-1@In Progress@25", "T-1", "In Progress", MIDNIGHT + 25)


def _snapshot(store: HistoryStore) -> tuple:
    return _steps(store), _cases(store), _intervals(store)


def _wipe(store: HistoryStore) -> None:
    with store.engine.begin() as db:
        for table in ("starpulse_step_summaries", "starpulse_cases", "starpulse_lane_intervals"):
            db.execute(text(f"DELETE FROM {table}"))


def test_the_start_up_pass_builds_what_recording_would_have_and_a_second_run_changes_nothing(
    store: HistoryStore,
) -> None:
    _fill(store)
    recorded = _snapshot(store)
    assert store.summary_differences() == []
    _wipe(store)
    assert _snapshot(store) == ([], [], [])
    assert store.summary_differences() != [], "empty summaries over raw rows are a difference"

    store.build_summaries()

    assert _snapshot(store) == recorded
    assert store.summary_differences() == []
    store.build_summaries()
    assert _snapshot(store) == recorded


def test_opening_a_store_whose_summaries_are_empty_builds_them(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    first = HistoryStore(url, MACHINES)
    _fill(first)
    recorded = _snapshot(first)
    _wipe(first)

    assert _snapshot(HistoryStore(url, MACHINES)) == recorded


def test_the_start_up_pass_leaves_summaries_that_already_exist_alone(store: HistoryStore) -> None:
    _fill(store)
    with store.engine.begin() as db:
        db.execute(text("UPDATE starpulse_step_summaries SET steps = steps + 5"))
    tampered = _snapshot(store)

    store.build_summaries()

    assert _snapshot(store) == tampered


def test_the_consistency_check_names_each_summary_that_differs_from_the_raw_rows(store: HistoryStore) -> None:
    _fill(store)
    with store.engine.begin() as db:
        db.execute(text("UPDATE starpulse_step_summaries SET steps = steps + 5 WHERE to_state = 'red_proven'"))
        db.execute(text("UPDATE starpulse_cases SET state = 'start' WHERE case_id = 'PROJ-7'"))
        db.execute(text("DELETE FROM starpulse_lane_intervals WHERE lane = 'Ready'"))

    differences = store.summary_differences()

    assert len(differences) == 3
    assert [d.split(":")[0] for d in differences] == [
        "starpulse_step_summaries",
        "starpulse_cases",
        "starpulse_lane_intervals",
    ]
    store.rebuild_summaries()
    assert store.summary_differences() == []
