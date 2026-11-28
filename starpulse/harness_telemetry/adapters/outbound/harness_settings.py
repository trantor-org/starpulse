"""The harness config `PUT /api/harnesses` keeps in the history store, over the one the config file declares."""

import logging
from typing import TYPE_CHECKING

from starpulse.harness_telemetry.model.harnesses import HarnessError, Harnesses, parse_harnesses

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

KEY = "harnesses"


class HarnessSettings:
    """The kept harness config, or the declared one while none is kept or the kept one no longer parses."""

    def __init__(self, log: EventLog, declared: Harnesses) -> None:
        self._log = log
        self.declared = declared

    def read(self) -> Harnesses:
        try:
            return self.current()
        except Exception as exc:  # fail closed: a reader sees the declared config while the store is unreadable
            logger.warning("harness settings: reading %s failed: %s", KEY, exc)
            return self.declared

    def current(self) -> Harnesses:
        """The kept config, or the declared one while none is kept; raises when the store cannot be read, so a write
        never builds on the declared config over a kept one it failed to read."""
        kept = self._log.setting(KEY)
        if not isinstance(kept, dict):
            return self.declared
        try:
            return parse_harnesses(kept)
        except HarnessError as exc:
            logger.warning("harness settings: kept %s is invalid: %s", KEY, exc)
            return self.declared

    def write(self, harnesses: Harnesses) -> None:
        self._log.set_setting(KEY, harnesses.as_toml())
