"""The autopilot decision log: per-day verdicts with their reason, the starts and the first restore, kept with a retention."""

from __future__ import annotations

from datetime import datetime

from starpulse.scheduler.model.decision_log import EMPTY, RETENTION_DAYS, note

DAY = 86400.0
NOON = datetime(2026, 11, 2, 12, 0).astimezone().timestamp()


def test_verdicts_count_per_local_day_by_admission_or_the_reason_that_refused() -> None:
    kept = note(EMPTY, NOON, verdicts=["admitted", "refused/sessions"])
    kept = note(kept, NOON + 60, verdicts=["refused/sessions"])
    kept = note(kept, NOON + DAY, verdicts=["admitted"])

    assert kept["days"] == {
        "2026-11-02": {"admitted": 1, "refused/sessions": 2},
        "2026-11-03": {"admitted": 1},
    }


def test_each_start_keeps_its_task_and_time_and_a_restore_keeps_only_the_first() -> None:
    kept = note(EMPTY, NOON, started="TASK-1")
    kept = note(kept, NOON + 1, started="TASK-1", restored=True)
    kept = note(kept, NOON + 2, restored=True)

    assert kept["starts"] == [{"task": "TASK-1", "at": NOON}, {"task": "TASK-1", "at": NOON + 1}]
    assert kept["restored_at"] == NOON + 1


def test_a_note_leaves_the_log_it_was_given_unchanged() -> None:
    note(EMPTY, NOON, verdicts=["admitted"], started="TASK-1", restored=True)

    assert EMPTY == {"days": {}, "starts": [], "restored_at": None}


def test_days_and_starts_older_than_the_retention_are_dropped() -> None:
    old = note(EMPTY, NOON, verdicts=["admitted"], started="TASK-1")

    kept = note(old, NOON + (RETENTION_DAYS + 1) * DAY, verdicts=["refused/cpu"])

    assert list(kept["days"]) == [datetime.fromtimestamp(NOON + (RETENTION_DAYS + 1) * DAY).date().isoformat()]
    assert kept["starts"] == []
