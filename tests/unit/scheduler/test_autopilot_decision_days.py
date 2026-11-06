"""`starpulse_autopilot_decision_days` counts the local days since the switch row with a kept admission decision."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from starpulse.event_log.event_log import EventLog
from starpulse.scheduler.adapters.exposition import autopilot_exposition
from starpulse.scheduler.model.decision_log import KEY as DECISION_LOG_KEY
from starpulse.scheduler.model.toggle import KEY as SWITCH_KEY


def _day_count(text: str) -> int:
    (line,) = (ln for ln in text.splitlines() if ln.startswith("starpulse_autopilot_decision_days "))
    return int(line.split()[1])


def test_decision_days_counts_logged_days_from_the_switch_day_on(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    switched = datetime(2026, 10, 3, 12).timestamp()
    log.set_setting(SWITCH_KEY, True, updated_at=switched)
    days = {"2026-10-02": {"admitted": 1}, "2026-10-03": {"admitted": 2}, "2026-10-05": {"refused": 4}}
    log.put_state(DECISION_LOG_KEY, {"days": days, "starts": [], "restored_at": None})

    assert _day_count(autopilot_exposition(log)) == 2


def test_decision_days_is_zero_before_the_switch_is_written(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")

    assert _day_count(autopilot_exposition(log)) == 0
