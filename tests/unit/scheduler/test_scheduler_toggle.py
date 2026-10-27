"""The scheduler's switch is kept in the history store, so it survives a restart and needs no config edit."""

from pathlib import Path

from starpulse.event_log.event_log import EventLog
from starpulse.scheduler.model.toggle import Toggle


def _toggle(tmp_path: Path) -> Toggle:
    return Toggle(EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"))


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

