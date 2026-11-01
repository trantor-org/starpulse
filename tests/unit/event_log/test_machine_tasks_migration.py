"""The machine tasks' table: migration 0039 creates what the code declares, with its (machine, active_at) index."""

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select
from starpulse.event_log.readmodel.tables import machine_tasks
from starpulse.event_log.tables import checkpoints


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


def test_migration_0041_clears_the_machine_tasks_and_their_checkpoint_so_the_next_fold_rebuilds_them() -> None:
    migration = importlib.import_module("starpulse.event_log.migrations.versions.0041_refold_machine_tasks")
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        machine_tasks.create(db)
        checkpoints.create(db)
        db.execute(machine_tasks.insert().values(machine="ci", task="T-1", state="s", agent={}, active_at=1.0, seq=9))
        db.execute(checkpoints.insert().values(name="read-model:machine-tasks", position=9, schema_version=0, saved_at=1.0))
        db.execute(checkpoints.insert().values(name="read-model:tasks", position=5, schema_version=0, saved_at=1.0))
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        migration.upgrade()

    with engine.connect() as db:
        assert db.execute(select(machine_tasks.c.task)).all() == []
        assert db.execute(select(checkpoints.c.name)).scalars().all() == ["read-model:tasks"]
