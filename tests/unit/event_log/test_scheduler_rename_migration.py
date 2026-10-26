"""Migration 0028 moves an install's run ledger and settings from the Autopilot names to the Scheduler's."""

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from starpulse.event_log.tables import scheduler_runs

VERSIONS = "starpulse.event_log.migrations.versions."


def test_migration_0028_renames_the_ledger_table_its_index_and_the_settings_keys() -> None:
    first = importlib.import_module(VERSIONS + "0016_autopilot_runs")
    rename = importlib.import_module(VERSIONS + "0028_scheduler_names")
    engine = create_engine("sqlite://")
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        first.upgrade()
        db.execute(
            text(
                "CREATE TABLE starpulse_settings (key TEXT PRIMARY KEY, value JSON NOT NULL, updated_at FLOAT NOT NULL)"
            )
        )
        db.execute(
            text("INSERT INTO starpulse_settings VALUES ('autopilot.enabled', 'true', 1.0), ('level.window', '7', 2.0)")
        )
        db.execute(
            text(
                "INSERT INTO starpulse_autopilot_runs (task, tier, points, outcome, duration_s, peak, recorded_at) VALUES ('TASK-1', 'standard', 8, 'review', 1.0, '{}', 3.0)"
            )
        )
        rename.upgrade()
        keys = sorted(row[0] for row in db.execute(text("SELECT key FROM starpulse_settings")))
        runs = db.execute(text("SELECT task FROM starpulse_scheduler_runs")).all()

    inspector = inspect(engine)
    assert keys == ["level.window", "scheduler.enabled"]
    assert runs == [("TASK-1",)]
    assert {c["name"] for c in inspector.get_columns("starpulse_scheduler_runs")} == {
        c.name for c in scheduler_runs.columns
    }
    assert [i["name"] for i in inspector.get_indexes("starpulse_scheduler_runs")] == [
        "ix_starpulse_scheduler_runs_tier_points"
    ]
