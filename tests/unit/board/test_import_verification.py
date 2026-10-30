"""A board and its recorded runs import as Events, and replaying every Task is checked against its file."""

from __future__ import annotations

from pathlib import Path

from starpulse.board.adapters.board_import import import_board
from starpulse.board.adapters.task_history import KIND, WRITER
from starpulse.board.model.seam import OPERATOR
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.runs.application.commands.run_streams import RunStreams

_RECORD = {"title": "Cut over", "status": "Review", "labels": ["a"], "session": "s1"}
_LANES = [("e1", "TASK-1", "Ready", 10.0), ("e2", "TASK-1", "In Progress", 20.0), ("e3", "TASK-1", "Review", 30.0)]
_RUN = ("r1", {"workflow": "ci", "run_id": "7", "event": "StepStarted", "step": "lint", "time": 5.0})


def _store(tmp_path: Path) -> tuple[EventStore, object]:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    return EventStore(engine), engine


def test_lane_history_imports_as_transitioned_events_and_replay_equals_the_file(tmp_path: Path) -> None:
    store, engine = _store(tmp_path)

    report = import_board(store, {"TASK-1": _RECORD}, _LANES, [_RUN], RunStreams(store).record)

    events = store.read(KIND, "TASK-1")
    assert [event.type for event in events] == ["TaskImported", "Transitioned", "Transitioned", "Transitioned"]
    assert [event.at for event in events[1:]] == [10.0, 20.0, 30.0]
    assert (report.tasks, report.equal, report.differing, report.gaps, report.runs) == (1, 1, {}, [], 1)
    assert [event.type for event in RunStreams(store).read("ci", "7")] == ["StepStarted"]
    engine.dispose()


def test_a_gap_in_the_lane_history_is_imported_as_is_and_listed(tmp_path: Path) -> None:
    store, engine = _store(tmp_path)

    report = import_board(store, {"TASK-1": _RECORD}, _LANES[:2], [], RunStreams(store).record)

    assert report.gaps == ["TASK-1"]
    assert report.equal == 1
    assert store.read(KIND, "TASK-1")[-1].payload == {"from": "In Progress", "to": "Review", "imported": True}
    engine.dispose()


def test_a_second_import_adds_nothing_and_still_verifies(tmp_path: Path) -> None:
    store, engine = _store(tmp_path)
    import_board(store, {"TASK-1": _RECORD}, _LANES, [_RUN], RunStreams(store).record)

    report = import_board(store, {"TASK-1": _RECORD}, _LANES, [_RUN], RunStreams(store).record)

    assert len(store.read(KIND, "TASK-1")) == 4
    assert (report.imported, report.equal, report.runs_imported) == (0, 1, 0)
    engine.dispose()


def test_a_task_whose_file_moved_past_its_history_is_reconciled_and_listed(tmp_path: Path) -> None:
    store, engine = _store(tmp_path)
    import_board(store, {"TASK-1": _RECORD}, _LANES, [], RunStreams(store).record)
    moved = _RECORD | {"title": "Renamed"}

    report = import_board(store, {"TASK-1": moved}, _LANES, [], RunStreams(store).record)
    again = import_board(store, {"TASK-1": moved}, _LANES, [], RunStreams(store).record)

    assert (report.reconciled, report.differing, report.ok) == (["TASK-1"], {}, True)
    assert store.read(KIND, "TASK-1")[-1].type == "FieldsEdited"
    assert (again.reconciled, len(store.read(KIND, "TASK-1"))) == ([], 5)
    engine.dispose()


def test_lane_ids_match_the_records_display_status_and_leave_no_gap(tmp_path: Path) -> None:
    store, engine = _store(tmp_path)
    lanes = [("e1", "TASK-1", "ready", 10.0), ("e2", "TASK-1", "in_progress", 20.0)]

    report = import_board(store, {"TASK-1": _RECORD | {"status": "In Progress"}}, lanes, [], RunStreams(store).record)

    assert (report.gaps, report.equal) == ([], 1)
    assert [event.payload["to"] for event in store.read(KIND, "TASK-1")[1:]] == ["ready", "In Progress"]
    engine.dispose()


def test_a_task_whose_history_cannot_replay_is_listed_and_the_tasks_after_it_still_reconcile(tmp_path: Path) -> None:
    store, engine = _store(tmp_path)
    records = {"TASK-1": _RECORD, "TASK-2": {**_RECORD, "title": "Next"}}
    import_board(store, records, [], [], RunStreams(store).record)
    checked = NewEvent("CriterionChecked", {"kind": "ac", "n": 2, "checked": True}, OPERATOR, WRITER)
    store.append(KIND, "TASK-1", len(store.read(KIND, "TASK-1")), [checked])
    moved = {**records, "TASK-2": {**_RECORD, "title": "Renamed"}}

    report = import_board(store, moved, [], [], RunStreams(store).record)

    assert report.broken == ["TASK-1"]
    assert report.reconciled == ["TASK-2"]
    assert report.ok is False
    engine.dispose()
