"""Declared fields: `[board.fields]` is parsed, a Task's fields are checked against it, and each queried field is indexed."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.declared import (
    BadDeclaration,
    Declared,
    MistypedField,
    UndeclaredField,
    check_fields,
    declared_fields,
    ensure_columns,
)

_BOARD = {
    "type": "native",
    "fields": {
        "area": {"type": "string", "queried": True},
        "points": {"type": "integer", "queried": True},
        "note": {"type": "string"},
    },
}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine


def _columns(engine: Engine) -> set[str]:
    with engine.connect() as db:
        return {row[1] for row in db.execute(text("PRAGMA table_xinfo(starpulse_tasks)"))}


def _indexes(engine: Engine) -> set[str]:
    with engine.connect() as db:
        return {row[1] for row in db.execute(text("PRAGMA index_list(starpulse_tasks)"))}


def test_the_board_table_declares_each_field_with_its_type_and_whether_it_is_queried() -> None:
    assert declared_fields(_BOARD) == {
        "area": Declared("area", "string", True),
        "points": Declared("points", "integer", True),
        "note": Declared("note", "string", False),
    }
    assert declared_fields({"type": "native"}) == {}


@pytest.mark.parametrize(
    "fields",
    [
        {"Area": {"type": "string"}},
        {"a-b": {"type": "string"}},
        {"area": {"type": "date"}},
        {"area": {"queried": True}},
    ],
)
def test_a_declaration_with_a_bad_name_or_an_unknown_type_is_refused(fields: dict) -> None:
    with pytest.raises(BadDeclaration):
        declared_fields({"fields": fields})


def test_a_value_of_the_wrong_type_or_a_name_nobody_declared_is_refused() -> None:
    declared = declared_fields(_BOARD)
    check_fields(declared, {"area": "ops", "points": 3})

    with pytest.raises(MistypedField):
        check_fields(declared, {"points": "3"})
    with pytest.raises(MistypedField):
        check_fields(declared, {"points": True})
    with pytest.raises(UndeclaredField):
        check_fields(declared, {"colour": "red"})


def test_each_queried_field_gets_a_generated_column_and_a_partial_index_and_the_rest_get_none(engine: Engine) -> None:
    declared = declared_fields(_BOARD)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO starpulse_tasks (id, seq, version, created_at, updated_at, title, type, state, priority,"
                " milestone, assignee, archived, description, plan, notes, final_summary, labels, dependencies,"
                " 'references', documentation, modified_files, comments, fields, meta) VALUES ('TASK-1', 1, 1, 0, 0,"
                " '', '', '', '', '', '', 0, '', '', '', '', '[]', '[]', '[]', '[]', '[]', '[]',"
                " '{\"area\": \"ops\"}', '{}')"
            ).bindparams()
        )

    ensure_columns(engine, declared)
    ensure_columns(engine, declared)

    with engine.connect() as db:
        stored = db.execute(text("SELECT field_area FROM starpulse_tasks")).scalar_one()
        plan = db.execute(
            text("EXPLAIN QUERY PLAN SELECT id FROM starpulse_tasks WHERE archived = 0 AND field_area = 'ops'")
        ).all()
    assert (_columns(engine) >= {"field_area", "field_points"}, "field_note" in _columns(engine)) == (True, False)
    assert {"ix_starpulse_tasks_field_area", "ix_starpulse_tasks_field_points"} <= _indexes(engine)
    assert stored == "ops"
    assert "ix_starpulse_tasks_field_area" in str(plan)
