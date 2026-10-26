"""The scheduler's switch is kept in the history store, so it survives a restart and needs no config edit."""

import json
from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.scheduler.model.toggle import TOGGLE_FILE, Toggle


def _toggle(tmp_path: Path) -> Toggle:
    return Toggle(EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"), tmp_path / TOGGLE_FILE)


def test_the_scheduler_starts_off(tmp_path: Path) -> None:
    assert _toggle(tmp_path).get() is False


def test_the_switch_persists_across_a_restart(tmp_path: Path) -> None:
    _toggle(tmp_path).set(True)

    assert _toggle(tmp_path).get() is True  # a new instance is a restarted server

    _toggle(tmp_path).set(False)

    assert _toggle(tmp_path).get() is False


def test_the_switch_is_a_row_in_the_store_not_a_file(tmp_path: Path) -> None:
    _toggle(tmp_path).set(True)

    assert EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}").setting("scheduler.enabled") is True
    assert list(tmp_path.glob("starpulse-scheduler*")) == []


def test_a_switch_file_from_before_the_store_is_imported_once(tmp_path: Path) -> None:
    (tmp_path / TOGGLE_FILE).write_text(json.dumps({"enabled": True}))

    assert _toggle(tmp_path).get() is True

    _toggle(tmp_path).set(False)
    (tmp_path / TOGGLE_FILE).write_text(json.dumps({"enabled": True}))
    assert _toggle(tmp_path).get() is False  # the row wins; the file is not read again


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"enabled": "yes"}', '{"enabled": 1}', "{}"])
def test_a_switch_file_that_does_not_say_true_leaves_it_off(tmp_path: Path, text: str) -> None:
    (tmp_path / TOGGLE_FILE).write_text(text)

    assert _toggle(tmp_path).get() is False
