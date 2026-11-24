"""The Admin display and theme choices every device shares: one JSON value kept in the history store."""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

KEY = "admin.display"


class DisplaySettings:
    """What Admin kept for `display` and `theme`, read back as it was written; the request models own what a value may be."""

    def __init__(self, log: EventLog) -> None:
        self._log = log

    def read(self) -> dict[str, Any]:
        try:
            value = self._log.setting(KEY)
        except Exception as exc:  # fail closed: an unreadable value is no choice made
            logger.warning("display settings: reading %s failed: %s", KEY, exc)
            return {}
        return value if isinstance(value, dict) else {}

    def write(self, value: dict[str, Any]) -> None:
        self._log.set_setting(KEY, value)
