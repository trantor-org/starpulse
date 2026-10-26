"""Under the read model the assembled board is drawn without opening a task file: the Board's reader is never called."""

import dataclasses
import tempfile
from pathlib import Path

import pytest

from starpulse._internal.config.config import load
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.runtime import assembly


def test_the_assembled_feed_draws_and_reads_a_task_without_the_boards_file_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(*_: object, **__: object) -> None:
        raise AssertionError("a task file was opened")

    real = assembly.load_board

    def reading_nothing(*args: object, **kwargs: object) -> object:
        return dataclasses.replace(real(*args, **kwargs), read=refused, keys=None)

    monkeypatch.setattr(assembly, "load_board", reading_nothing)
    with tempfile.TemporaryDirectory() as directory:
        engine = EventLog(f"sqlite:///{Path(directory) / 'events.sqlite'}").engine
        created = NewEvent(
            "TaskCreated", {"title": "T", "description": "", "state": "Ready", "labels": []}, "a", "operator"
        )
        EventStore(engine).append("task", "TASK-1", 0, [created])
        Projector(engine, EventStore(engine)).catch_up()
        _, feed = assembly.assemble(load(None), Path(directory), None, [], ReadModel(engine))
        flows = feed.snapshot()["flows"]
        assert any(flow["name"] == "board" for flow in flows)
        assert feed.held("TASK-1")["id"] == "TASK-1"
        engine.dispose()
