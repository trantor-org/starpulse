"""The session caps an operator sets from StarPulse Admin: one per harness, kept in the history store, which override the
`[scheduler]` limits in `starpulse.toml` until cleared. The loop reads them on every pass, so a change needs no restart."""

from starpulse.event_log.event_log import EventLog
from starpulse.scheduler.model.override_store import OverrideStore

KEY = "scheduler.session_caps"


def _cap(value: object) -> int | None:
    """`value` when it is a whole number above zero, else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


class SessionCapSetting:
    """Each harness's cap in the store, or none: a harness with none, or one that cannot be read, keeps the config limit."""

    def __init__(self, log: EventLog) -> None:
        self.store = OverrideStore(log, KEY, _cap)

    def get(self, harness: str) -> int | None:
        return _cap(self.store.get(harness))

    def set(self, harness: str, value: object) -> None:
        """Keep `value` as `harness`'s cap, or with None clear it; anything but a whole number above zero raises
        ValueError and changes nothing."""
        if value is not None and _cap(value) is None:
            raise ValueError(f"session cap must be a whole number above zero; got {value!r}")
        caps = {name: cap for name, cap in self.store.all().items() if name != harness}
        if value is not None:
            caps[harness] = value
        self.store.save(caps)
