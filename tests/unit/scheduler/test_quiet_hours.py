"""Quiet hours: which instants a daily window holds, read on its zone's wall clock."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from starpulse.scheduler.model.quiet_hours import QuietHours, parse


def _phoenix(hour: int, minute: int) -> float:
    """An instant at the given Phoenix wall-clock time (MST, UTC-7, no daylight saving)."""
    return datetime(2026, 10, 12, hour, minute, tzinfo=timezone(timedelta(hours=-7))).timestamp()


def test_a_window_that_crosses_midnight_holds_the_night_on_its_zones_clock() -> None:
    quiet = QuietHours("22:00", "07:00", "America/Phoenix")

    assert all(quiet.contains(_phoenix(h, m)) for h, m in ((22, 0), (23, 30), (0, 0), (6, 59)))
    assert not any(quiet.contains(_phoenix(h, m)) for h, m in ((7, 0), (12, 0), (21, 59)))


def test_a_same_day_window_holds_only_its_own_hours() -> None:
    quiet = QuietHours("09:00", "17:30", "UTC")

    assert quiet.contains(datetime(2026, 10, 12, 9, 0, tzinfo=UTC).timestamp())
    assert not quiet.contains(datetime(2026, 10, 12, 17, 30, tzinfo=UTC).timestamp())
    assert not quiet.contains(datetime(2026, 10, 12, 8, 59, tzinfo=UTC).timestamp())


@pytest.mark.parametrize("clock", ["1230Z", "12:3Z", "1230+", "12 30"])
def test_a_clock_without_a_colon_or_with_a_zone_is_refused_at_parse(clock: str) -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        parse({"start": clock, "end": "17:30", "timezone": "UTC"})
