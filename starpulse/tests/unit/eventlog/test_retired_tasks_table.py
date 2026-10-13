"""The retired tasks' table: migration 0017 creates what the code declares, and pruning the event log keeps it."""

import importlib
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, inspect, select

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.tables import retired_tasks


def test_migration_0017_creates_the_retired_tasks_table_the_code_declares() -> None:
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module("starpulse._internal.eventlog.migrations.versions.0017_retired_tasks")
    engine = create_engine("sqlite://")
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        migration.upgrade()

    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("starpulse_retired_tasks")} == {c.name for c in retired_tasks.columns}
    assert inspector.get_pk_constraint("starpulse_retired_tasks")["constrained_columns"] == ["task"]


def test_pruning_the_event_log_keeps_every_retired_task(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")
    with log.engine.begin() as db:
        db.execute(insert(retired_tasks).values(task="TASK-1", name="task-1.md", text="---\n", retired_at=0.0))
    log.append("board", {"kind": "old"})

    assert log.prune(0, now=time.time() + 86400, archive_dir=tmp_path / "archive") == 1

    with log.engine.connect() as db:
        assert db.execute(select(retired_tasks.c.task)).scalars().all() == ["TASK-1"]
