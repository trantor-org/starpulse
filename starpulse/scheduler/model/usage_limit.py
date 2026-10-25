"""Parse a harness usage or credit limit from the text a start or stop names."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_LIMIT = re.compile(
    r"usage limit|weekly limit|credit limit|out of credits|hit your (?:usage|weekly|credit)",
    re.I,
)
_RESET = re.compile(
    r"resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([^)]+)\))?",
    re.I,
)
FIVE_HOURS = 5 * 3600


def until(text: str, now: float) -> float | None:
    """The epoch second admission for this harness may resume, or None when `text` is not a usage limit."""
    if _LIMIT.search(text) is None:
        return None
    found = _RESET.search(text)
    if found is None:
        return now + FIVE_HOURS
    hour = int(found[1])
    minute = int(found[2] or 0)
    meridiem = (found[3] or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    zone_name = (found[4] or "UTC").strip()
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        zone = ZoneInfo("UTC")
    local = datetime.fromtimestamp(now, zone)
    reset_clock = time(hour, minute)
    reset = datetime.combine(local.date(), reset_clock, zone)
    if reset.timestamp() <= now:
        reset = datetime.combine(local.date() + timedelta(days=1), reset_clock, zone)
    return reset.timestamp()
