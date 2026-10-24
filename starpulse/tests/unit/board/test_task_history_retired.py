"""A retired task's text becomes its History: `TaskImported` of its record, then `Archived`, once."""

from __future__ import annotations

from pathlib import Path

from starpulse._internal.board.task_history import KIND, TaskHistory
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.rows import load
from starpulse.event_log.store import EventStore

_TEXT = "---\nid: TASK-1\ntitle: Retire the cron\nstatus: Done\n---\n"


def _parse(text: str) -> dict[str, object]:
    return {"title": "Retire the cron", "status": "Done", "labels": ["a"]}


def test_a_retired_row_becomes_imported_then_archived_and_a_second_import_adds_nothing(tmp_path: Path) -> None:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    store, history = EventStore(engine), TaskHistory()
    history.attach(engine)

    history.import_retired([("TASK-1", _TEXT)], _parse)
    history.import_retired([("TASK-1", _TEXT)], _parse)

    assert [event.type for event in store.read(KIND, "TASK-1")] == ["TaskImported", "Archived"]
    Projector(engine, store).catch_up()
    with engine.connect() as db:
        row = load(db, "TASK-1")
    assert (row["title"], row["state"], row["archived"], row["labels"]) == ("Retire the cron", "Done", True, ["a"])
    engine.dispose()
