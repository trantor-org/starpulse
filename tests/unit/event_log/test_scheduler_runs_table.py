"""The scheduler run ledger's table: migrations 0016 and 0028 create what the code declares, and pruning the event log keeps it."""

import importlib
import time
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import scheduler_runs
from starpulse.scheduler.model.ledger import Ledger, RunRecord


def test_migrations_create_the_scheduler_runs_table_the_code_declares() -> None:
    versions = "starpulse.event_log.migrations.versions."
    first = importlib.import_module(versions + "0016_autopilot_runs")
    rename = importlib.import_module(versions + "0028_scheduler_names")
    engine = create_engine("sqlite://")
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        first.upgrade()
        db.execute(text("CREATE TABLE starpulse_settings (key TEXT PRIMARY KEY)"))
        rename.upgrade()

    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("starpulse_scheduler_runs")} == {
        c.name for c in scheduler_runs.columns
    }
    assert [i["column_names"] for i in inspector.get_indexes("starpulse_scheduler_runs")] == [["tier", "points"]]


def test_pruning_the_event_log_keeps_every_recorded_run(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")
    Ledger(log, tmp_path / "runs.jsonl").record(RunRecord("TASK-1", "standard", 8, "review", 60.0, {"cpu": 10.0}))
    log._append("board", {"kind": "old"})

    pruned = log.prune(0, now=time.time() + 86400, archive_dir=tmp_path / "archive")

    assert pruned == 1  # the event went
    with log.engine.connect() as db:
        assert len(db.execute(select(scheduler_runs)).all()) == 1
