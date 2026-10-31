"""The session caps an operator sets from StarPulse Admin: one per harness, kept in the history store, which override the
`[scheduler]` limits in `starpulse.toml` until cleared. The loop reads them on every pass, so a change needs no restart."""

import logging

from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

KEY = "scheduler.session_caps"


def _cap(value: object) -> int | None:
    """`value` when it is a whole number above zero, else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


class SessionCapSetting:
    """Each harness's cap in the store, or none: a harness with none, or one that cannot be read, keeps the config limit."""

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def _stored(self) -> dict[str, object]:
        raw = self.log.setting(KEY)
        return raw if isinstance(raw, dict) else {}

    def get(self, harness: str) -> int | None:
        try:
            return _cap(self._stored().get(harness))
        except Exception as exc:  # an unreadable cap is no override; the config limit still holds
            logger.warning("StarPulse scheduler: reading the session caps failed: %s", exc)
            return None

    def set(self, harness: str, value: object) -> None:
        """Keep `value` as `harness`'s cap, or with None clear it; anything but a whole number above zero raises
        ValueError and changes nothing."""
        if value is not None and _cap(value) is None:
            raise ValueError(f"session cap must be a whole number above zero; got {value!r}")
        caps = {name: cap for name, cap in self._stored().items() if name != harness and _cap(cap) is not None}
        if value is not None:
            caps[harness] = value
        if caps:
            self.log.set_setting(KEY, caps)
        else:
            self.log.delete_setting(KEY)
