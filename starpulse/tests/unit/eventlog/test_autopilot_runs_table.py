"""The autopilot run ledger's table: migration 0016 creates what the code declares, and pruning the event log keeps it."""

import importlib
import time
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select

from starpulse._internal.autopilot.ledger import Ledger, RunRecord
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.tables import autopilot_runs


def test_migration_0016_creates_the_autopilot_runs_table_the_code_declares() -> None:
    migration = importlib.import_module("starpulse._internal.eventlog.migrations.versions.0016_autopilot_runs")
    engine = create_engine("sqlite://")
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        migration.upgrade()

    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("starpulse_autopilot_runs")} == {c.name for c in autopilot_runs.columns}
    assert [i["column_names"] for i in inspector.get_indexes("starpulse_autopilot_runs")] == [["tier", "points"]]


def test_pruning_the_event_log_keeps_every_recorded_run(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")
    Ledger(log, tmp_path / "runs.jsonl").record(RunRecord("TASK-1", "standard", 8, "review", 60.0, {"cpu": 10.0}))
    log.append("board", {"kind": "old"})

    pruned = log.prune(0, now=time.time() + 86400, archive_dir=tmp_path / "archive")

    assert pruned == 1  # the event went
    with log.engine.connect() as db:
        assert len(db.execute(select(autopilot_runs)).all()) == 1
