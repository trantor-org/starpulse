"""`starpulse migrate --config FILE`: a fresh store is brought to its schema and summaries; a second run changes no schema.

The operator state once kept in files (the scheduler switch, the history window, the run ledger) moves into the store
once, and each file is retired."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from starpulse.board.adapters.history_window import KEY as WINDOW_KEY
from starpulse.board.adapters.history_window import SETTINGS_FILE
from starpulse.event_log.event_log import EventLog
from starpulse.runtime import store_migrate
from starpulse.runtime.store_migrate import RETIRED_SUFFIX
from starpulse.scheduler.model.ledger import LEDGER_FILE, Ledger, RunRecord
from starpulse.scheduler.model.toggle import KEY as TOGGLE_KEY
from starpulse.scheduler.model.toggle import TOGGLE_FILE


def _schema(url: str) -> list[tuple[str]]:
    with create_engine(url).connect() as db:
        return [
            tuple(row) for row in db.execute(text("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"))
        ]


def test_migrate_brings_a_fresh_store_up_and_a_second_run_exits_zero_with_no_schema_change(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'store.sqlite'}"
    config = tmp_path / "starpulse.toml"
    config.write_text(f'database_url = "{url}"\n')

    assert store_migrate.main(["--config", str(config)]) == 0
    migrated = _schema(url)
    assert migrated

    assert store_migrate.main(["--config", str(config)]) == 0
    assert _schema(url) == migrated


def _run(task: str) -> RunRecord:
    return RunRecord(task, "standard", 8, "review", 120.0, {"cpu": 10, "memory": 6})


@pytest.fixture
def url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'store.sqlite'}"


def _migrate(url: str, tmp_path: Path) -> EventLog:
    store_migrate.maintain(url, {}, None, base=tmp_path, state_dir="state")
    return EventLog(url)


def _retired(file: Path) -> Path:
    return file.with_name(file.name + RETIRED_SUFFIX)


def test_a_settings_file_is_imported_once_keeping_its_age_and_retired(url: str, tmp_path: Path) -> None:
    toggle = tmp_path / "state" / TOGGLE_FILE
    toggle.parent.mkdir()
    toggle.write_text(json.dumps({"enabled": True}))
    os.utime(toggle, (1_000_000.0, 1_000_000.0))
    window = tmp_path / SETTINGS_FILE
    window.write_text(json.dumps({"history_hours": 12}))

    log = _migrate(url, tmp_path)

    assert (log.setting(TOGGLE_KEY), log.setting(WINDOW_KEY)) == (True, 12)
    assert log.setting_updated_at(TOGGLE_KEY) == 1_000_000.0
    assert not toggle.exists()
    assert not window.exists()
    assert json.loads(_retired(toggle).read_text()) == {"enabled": True}


def test_a_file_written_after_the_import_is_ignored_by_a_second_run(url: str, tmp_path: Path) -> None:
    window = tmp_path / SETTINGS_FILE
    window.write_text(json.dumps({"history_hours": 12}))
    _migrate(url, tmp_path)

    window.write_text(json.dumps({"history_hours": 48}))
    log = _migrate(url, tmp_path)

    assert log.setting(WINDOW_KEY) == 12
    assert not window.exists()


def test_a_stored_setting_wins_over_its_file_and_the_file_is_retired(url: str, tmp_path: Path) -> None:
    store_migrate.maintain(url, {}, None)
    EventLog(url).set_setting(WINDOW_KEY, 6)
    window = tmp_path / SETTINGS_FILE
    window.write_text(json.dumps({"history_hours": 48}))

    log = _migrate(url, tmp_path)

    assert log.setting(WINDOW_KEY) == 6
    assert not window.exists()
    assert _retired(window).exists()


@pytest.mark.parametrize("text", ["", "not json", "[]", "{}", '{"other": 1}'])
def test_a_settings_file_that_holds_no_value_is_retired_and_the_setting_stays_unset(
    url: str, tmp_path: Path, text: str
) -> None:
    window = tmp_path / SETTINGS_FILE
    window.write_text(text)

    log = _migrate(url, tmp_path)

    assert log.setting(WINDOW_KEY) is None
    assert not window.exists()


def test_a_ledger_file_is_imported_once_stamped_with_its_age_and_retired(url: str, tmp_path: Path) -> None:
    ledger = tmp_path / "state" / LEDGER_FILE
    ledger.parent.mkdir()
    ledger.write_text("".join(json.dumps(asdict(_run(task))) + "\n" for task in ("TASK-1", "TASK-2")))

    log = _migrate(url, tmp_path)

    assert [run.task for run in Ledger(log).runs()] == ["TASK-1", "TASK-2"]
    assert not ledger.exists()
    assert _retired(ledger).exists()


def test_a_store_that_already_holds_runs_ignores_a_ledger_file_and_retires_it(url: str, tmp_path: Path) -> None:
    store_migrate.maintain(url, {}, None)
    Ledger(EventLog(url)).record(_run("TASK-1"))
    ledger = tmp_path / "state" / LEDGER_FILE
    ledger.parent.mkdir()
    ledger.write_text(json.dumps(asdict(_run("TASK-9"))) + "\n")

    log = _migrate(url, tmp_path)

    assert [run.task for run in Ledger(log).runs()] == ["TASK-1"]
    assert not ledger.exists()


def test_the_command_reads_the_state_dir_from_the_config(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'store.sqlite'}"
    config = tmp_path / "starpulse.toml"
    config.write_text(f'database_url = "{url}"\n[scheduler]\nstate_dir = "state"\n')
    toggle = tmp_path / "state" / TOGGLE_FILE
    toggle.parent.mkdir()
    toggle.write_text(json.dumps({"enabled": True}))

    assert store_migrate.main(["--config", str(config)]) == 0

    assert EventLog(url).setting(TOGGLE_KEY) is True
    assert not toggle.exists()
