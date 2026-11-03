"""One history-store setting holding an operator's `{name: value}` overrides of the `starpulse.toml` scheduler limits: the
read and write the session caps and the cpu and memory limits share."""

import logging
from collections.abc import Callable, Mapping

from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)


class OverrideStore:
    """The overrides kept under `key`, each only while `valid` returns it: a value `valid` refuses, or a store that
    cannot be read, is no override and the config limit still holds."""

    def __init__(self, log: EventLog, key: str, valid: Callable[[object], object | None]) -> None:
        self.log = log
        self.key = key
        self.valid = valid

    def all(self) -> dict[str, object]:
        try:
            raw = self.log.setting(self.key)
            stored = raw if isinstance(raw, dict) else {}
            return {name: value for name, value in stored.items() if self.valid(value) is not None}
        except Exception as exc:  # an unreadable override is none; the config limit still holds
            logger.warning("StarPulse scheduler: reading %s failed: %s", self.key, exc)
            return {}

    def get(self, name: str) -> object | None:
        return self.all().get(name)

    def save(self, overrides: Mapping[str, object]) -> None:
        """Keep exactly `overrides`; none left deletes the setting."""
        if overrides:
            self.log.set_setting(self.key, dict(overrides))
        else:
            self.log.delete_setting(self.key)
