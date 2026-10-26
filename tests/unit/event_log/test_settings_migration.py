"""The settings table: the event log keeps operator settings in it, and migration 0015 creates the table the code declares."""

import importlib
import time
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import settings


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def test_a_setting_is_kept_replaced_and_deleted(log: EventLog) -> None:
    assert log.setting("scheduler.enabled") is None

    log.set_setting("scheduler.enabled", True)
    assert log.setting("scheduler.enabled") is True

    log.set_setting("scheduler.enabled", False)
    assert log.setting("scheduler.enabled") is False

    log.delete_setting("scheduler.enabled")
    assert log.setting("scheduler.enabled") is None


def test_a_setting_remembers_when_it_was_last_written(log: EventLog) -> None:
    assert log.setting_updated_at("scheduler.enabled") is None

    before = time.time()
    log.set_setting("scheduler.enabled", True)

    assert before <= (log.setting_updated_at("scheduler.enabled") or 0) <= time.time()


def test_settings_outlive_the_log_object(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'events.sqlite'}"
    EventLog(url).set_setting("history.hours", 12)

    assert EventLog(url).setting("history.hours") == 12


def test_migration_0015_creates_the_settings_table_the_code_declares() -> None:
    migration = importlib.import_module("starpulse.event_log.migrations.versions.0015_settings")
    engine = create_engine("sqlite://")
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        migration.upgrade()

    columns = {c["name"]: c for c in inspect(engine).get_columns("starpulse_settings")}
    assert set(columns) == {c.name for c in settings.columns}
    assert inspect(engine).get_pk_constraint("starpulse_settings")["constrained_columns"] == ["key"]
