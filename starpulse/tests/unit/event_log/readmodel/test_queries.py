"""The read model's queries answer from the projected tables, each by index and none by scanning the board."""

import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Engine, Select, text
from sqlalchemy.dialects import sqlite

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel import queries
from starpulse.event_log.readmodel.declared import declared_fields, ensure_columns
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.readmodel.rows import load
from starpulse.event_log.store import EventStore, NewEvent

_DECLARED = declared_fields({"fields": {"area": {"type": "string", "queried": True}}})


def _new(type: str, **payload: object) -> NewEvent:
    return NewEvent(type=type, payload=payload, actor="adin", writer="operator")


def _add(store: EventStore, task: str, *events: NewEvent) -> None:
    store.append("task", task, store.head("task", task), list(events))


@pytest.fixture
def board() -> Iterator[tuple[Engine, EventStore, ReadModel]]:
    with tempfile.TemporaryDirectory() as directory:
        engine = EventLog(f"sqlite:///{Path(directory) / 'events.sqlite'}").engine
        ensure_columns(engine, _DECLARED)
        yield engine, EventStore(engine), ReadModel(engine, _DECLARED)
        engine.dispose()


def _project(engine: Engine, store: EventStore) -> None:
    Projector(engine, store).catch_up()


def _seed(store: EventStore) -> None:
    _add(store, "TASK-1", _new("TaskCreated", title="one", state="Ready", fields={"area": "ops"}))
    _add(store, "TASK-2", _new("TaskCreated", title="two", state="Ready", dependencies=["TASK-1"]))
    _add(store, "TASK-3", _new("TaskCreated", title="three", state="Done", fields={"area": "ops"}))
    _add(store, "TASK-4", _new("TaskCreated", title="four", state="Ready", dependencies=["TASK-3"]))
    _add(store, "TASK-5", _new("TaskCreated", title="five", state="Ready", fields={"area": "ops"}), _new("Archived"))


def _plan(engine: Engine, statement: Select) -> list[str]:
    sql = str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    with engine.connect() as db:
        return [row[3] for row in db.execute(text(f"EXPLAIN QUERY PLAN {sql}"))]


def _scans(plan: list[str]) -> list[str]:
    return [line for line in plan if re.match(r"SCAN\b", line) and "USING" not in line and "VIRTUAL" not in line]


def test_the_snapshot_is_the_unarchived_tasks_by_state(board) -> None:
    engine, store, model = board
    _seed(store)
    _project(engine, store)

    assert [item["id"] for item in model.snapshot()] == ["TASK-1", "TASK-2", "TASK-3", "TASK-4"]
    assert [item["id"] for item in model.snapshot("Ready")] == ["TASK-1", "TASK-2", "TASK-4"]
    assert model.snapshot("Ready")[0]["title"] == "one"


def test_a_task_loads_whole_archived_or_not_and_is_none_when_unknown(board) -> None:
    engine, store, model = board
    _seed(store)
    _project(engine, store)

    with engine.connect() as db:
        assert model.task("TASK-5") == load(db, "TASK-5")
    assert model.task("TASK-5")["archived"] is True
    assert model.task("TASK-99") is None


def test_a_queried_declared_field_selects_unarchived_tasks_and_an_unqueried_one_is_refused(board) -> None:
    engine, store, model = board
    _seed(store)
    _project(engine, store)

    assert model.with_field("area", "ops") == ["TASK-1", "TASK-3"]
    with pytest.raises(KeyError):
        model.with_field("colour", "red")


def test_the_ready_set_holds_tasks_whose_dependencies_are_all_done(board) -> None:
    engine, store, model = board
    _seed(store)
    _project(engine, store)

    assert model.ready("Ready", "Done") == ["TASK-1", "TASK-4"]


def test_deltas_since_a_cursor_come_in_change_order_with_archived_tasks_and_page(board) -> None:
    engine, store, model = board
    _seed(store)
    _project(engine, store)
    everything = model.since(0)
    cursor = everything[1]["seq"]
    _add(store, "TASK-1", _new("Transitioned", to="Done"))
    _project(engine, store)

    assert [item["id"] for item in everything] == ["TASK-1", "TASK-2", "TASK-3", "TASK-4", "TASK-5"]
    assert [item["id"] for item in model.since(cursor)] == ["TASK-3", "TASK-4", "TASK-5", "TASK-1"]
    assert [item["id"] for item in model.since(cursor, limit=2)] == ["TASK-3", "TASK-4"]
    assert model.since(cursor)[-1]["archived"] is False and model.since(cursor)[-2]["archived"] is True


@pytest.mark.parametrize(
    "statement",
    [
        queries.snapshot(),
        queries.snapshot("Ready"),
        queries.live_criteria(),
        queries.with_field("field_area", "ops"),
        queries.ready("Ready", "Done"),
        queries.since(10, 100),
    ],
    ids=["snapshot", "snapshot-by-state", "live-criteria", "by-field", "ready", "since"],
)
def test_every_query_reads_through_an_index_and_never_scans_the_table(board, statement: Select) -> None:
    engine, _, _ = board
    plan = _plan(engine, statement)

    assert _scans(plan) == []
    assert any("ix_starpulse_tasks_" in line or "autoindex" in line for line in plan)


def test_the_live_queries_use_partial_indexes_so_archived_tasks_cost_nothing(board) -> None:
    engine, _, _ = board

    assert any("ix_starpulse_tasks_live_state" in line for line in _plan(engine, queries.snapshot("Ready")))
    assert any("ix_starpulse_tasks_live_id" in line for line in _plan(engine, queries.snapshot()))
    assert any("ix_starpulse_tasks_field_area" in line for line in _plan(engine, queries.with_field("field_area", "x")))
    assert any("ix_starpulse_tasks_seq" in line for line in _plan(engine, queries.since(10, 100)))
