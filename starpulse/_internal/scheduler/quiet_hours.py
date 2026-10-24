"""The scheduler's quiet hours: a daily window, set from StarPulse Admin and kept in the history store, in which the loop
admits nothing. Sessions already running continue, and the loop still finishes and settles them; only admission stops.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

KEY = "scheduler.quiet_hours"


@dataclass(frozen=True)
class QuietHours:
    """From `start` up to but not including `end`, both `HH:MM` on the wall clock of the IANA `timezone`.

    A window whose `end` comes before its `start` runs past midnight.
    """

    start: str
    end: str
    timezone: str

    def contains(self, at: float) -> bool:
        """Whether the epoch second `at` falls inside the window."""
        now = datetime.fromtimestamp(at, ZoneInfo(self.timezone)).time()
        start, end = time.fromisoformat(self.start), time.fromisoformat(self.end)
        return start <= now < end if start < end else now >= start or now < end


def _clock(value: object, key: str) -> str:
    try:
        if isinstance(value, str) and len(value) == 5:
            time.fromisoformat(value)
            return value
    except ValueError:
        pass
    raise ValueError(f"quiet hours {key} must be a time of day as HH:MM; got {value!r}")


def parse(raw: object) -> QuietHours:
    """`{"start": "HH:MM", "end": "HH:MM", "timezone": "<IANA zone>"}` as a window; a ValueError names what is wrong."""
    if not isinstance(raw, dict) or raw.keys() != {"start", "end", "timezone"}:
        raise ValueError('quiet hours take {"start": "HH:MM", "end": "HH:MM", "timezone": "<IANA zone>"}')
    start, end = _clock(raw["start"], "start"), _clock(raw["end"], "end")
    if start == end:
        raise ValueError("quiet hours start and end must differ")
    zone = raw["timezone"]
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError(f"quiet hours timezone must be an IANA zone name such as America/Phoenix; got {zone!r}") from None
    return QuietHours(start, end, zone)


class QuietHoursSetting:
    """The window in the store, or none: with none, or one that cannot be read, the clock holds nothing back."""

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def get(self) -> QuietHours | None:
        try:
            raw = self.log.setting(KEY)
            return None if raw is None else parse(raw)
        except Exception as exc:  # an unreadable window is no window; the switch still decides
            logger.warning("StarPulse scheduler: reading the quiet hours failed: %s", exc)
            return None

    def state(self) -> dict[str, Any] | None:
        """The window as `GET /api/scheduler` serves it, or None."""
        quiet = self.get()
        return None if quiet is None else asdict(quiet)

    def set(self, raw: object) -> None:
        """Keep `raw` as the window, or with None clear it; a value `parse` refuses raises ValueError and changes nothing."""
        if raw is None:
            self.log.delete_setting(KEY)
        else:
            self.log.set_setting(KEY, asdict(parse(raw)))
