"""An operator setting once kept in a JSON file beside the config moves into the history store once, then the file is retired."""

import json
import os
from pathlib import Path

import pytest

from starpulse._internal.eventlog import operator_settings as settings
from starpulse._internal.eventlog.event_log import EventLog

KEY = "scheduler.enabled"


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    return tmp_path / "starpulse-autopilot.json"


def test_a_setting_with_no_row_and_no_file_reads_as_unset(log: EventLog, legacy: Path) -> None:
    assert settings.read(log, KEY, legacy, "enabled") is None


def test_an_existing_file_is_imported_once_and_retired(log: EventLog, legacy: Path) -> None:
    legacy.write_text(json.dumps({"enabled": True}))

    assert settings.read(log, KEY, legacy, "enabled") is True

    assert log.setting(KEY) is True
    assert not legacy.exists()
    assert legacy.with_name(legacy.name + ".imported").read_text() == json.dumps({"enabled": True})


def test_an_imported_setting_keeps_the_time_its_file_was_last_written(log: EventLog, legacy: Path) -> None:
    legacy.write_text(json.dumps({"enabled": True}))
    os.utime(legacy, (1_000_000.0, 1_000_000.0))

    settings.read(log, KEY, legacy, "enabled")

    assert log.setting_updated_at(KEY) == 1_000_000.0


def test_a_file_written_after_the_import_is_ignored(log: EventLog, legacy: Path) -> None:
    legacy.write_text(json.dumps({"enabled": True}))
    settings.read(log, KEY, legacy, "enabled")

    legacy.write_text(json.dumps({"enabled": False}))

    assert settings.read(log, KEY, legacy, "enabled") is True


def test_a_stored_value_wins_over_a_file_beside_it(log: EventLog, legacy: Path) -> None:
    log.set_setting(KEY, False)
    legacy.write_text(json.dumps({"enabled": True}))

    assert settings.read(log, KEY, legacy, "enabled") is False
    assert legacy.exists()


@pytest.mark.parametrize("text", ["", "not json", "[]", "{}", '{"other": 1}'])
def test_a_file_that_holds_no_value_is_retired_and_reads_as_unset(log: EventLog, legacy: Path, text: str) -> None:
    legacy.write_text(text)

    assert settings.read(log, KEY, legacy, "enabled") is None

    assert log.setting(KEY) is None
    assert not legacy.exists()


def test_a_store_that_cannot_be_opened_reads_as_unset_and_keeps_the_file(tmp_path: Path, legacy: Path) -> None:
    unreachable = EventLog(f"sqlite:///{tmp_path / 'missing' / 'history.sqlite'}")
    legacy.write_text(json.dumps({"enabled": True}))

    assert settings.read(unreachable, KEY, legacy, "enabled") is None

    assert legacy.exists()


def test_writing_a_setting_retires_a_file_that_would_otherwise_be_imported_later(log: EventLog, legacy: Path) -> None:
    legacy.write_text(json.dumps({"enabled": True}))

    settings.write(log, KEY, False, legacy)

    assert settings.read(log, KEY, legacy, "enabled") is False
    assert not legacy.exists()


def test_clearing_a_setting_does_not_let_a_stale_file_come_back(log: EventLog, legacy: Path) -> None:
    legacy.write_text(json.dumps({"enabled": True}))

    settings.clear(log, KEY, legacy)

    assert settings.read(log, KEY, legacy, "enabled") is None
