"""A board and its recorded runs import as Events, and replaying every Task is checked against its file."""

from __future__ import annotations

from pathlib import Path

from starpulse._internal.board.board_import import import_board
from starpulse._internal.board.task_history import KIND
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.runs.run_streams import RunStreams
from starpulse._internal.store import EventStore

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


def test_a_lane_history_that_ends_elsewhere_than_the_file_is_imported_as_is_and_listed(tmp_path: Path) -> None:
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


def test_a_task_whose_file_changed_since_its_history_is_reported_differing(tmp_path: Path) -> None:
    store, engine = _store(tmp_path)
    import_board(store, {"TASK-1": _RECORD}, _LANES, [], RunStreams(store).record)

    report = import_board(store, {"TASK-1": _RECORD | {"title": "Renamed"}}, _LANES, [], RunStreams(store).record)

    assert report.differing == {"TASK-1": ["title"]}
    assert not report.ok
    engine.dispose()
