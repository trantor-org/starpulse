"""The scheduler's selected harness: the one it starts and whose session cap and credit pause apply."""

from __future__ import annotations

import logging

from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

KEY = "scheduler.harness"
DEFAULT = "claude"


class HarnessSetting:
    """The harness name in the store; missing or unreadable rows read as `claude`."""

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def get(self) -> str:
        try:
            raw = self.log.setting(KEY)
        except Exception as exc:
            logger.warning("StarPulse scheduler: reading the harness failed: %s", exc)
            return DEFAULT
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return DEFAULT

    def set(self, value: object) -> None:
        """Keep a non-empty harness name; anything else raises ValueError."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError('harness must be a non-empty name such as "claude" or "cursor"')
        self.log.set_setting(KEY, value.strip())
