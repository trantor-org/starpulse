"""The machine tasks' table: migration 0039 creates what the code declares, with its (machine, active_at) index."""

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from starpulse.event_log.readmodel.tables import machine_tasks


def test_migration_0039_creates_the_machine_tasks_table_the_code_declares() -> None:
    migration = importlib.import_module("starpulse.event_log.migrations.versions.0039_machine_tasks")
    engine = create_engine("sqlite://")
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        migration.upgrade()

    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("starpulse_machine_tasks")} == {c.name for c in machine_tasks.columns}
    assert inspector.get_pk_constraint("starpulse_machine_tasks")["constrained_columns"] == ["machine", "task"]
    indexed = {tuple(index["column_names"]) for index in inspector.get_indexes("starpulse_machine_tasks")}
    assert ("machine", "active_at") in indexed
