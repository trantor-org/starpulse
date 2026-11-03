"""The cpu and memory limits an operator sets from StarPulse Admin: kept in the history store, they override the
`[scheduler.limits]` in `starpulse.toml` until cleared. The sampler reads them on every reading, so a change needs no
restart."""

import logging
import math
from collections.abc import Mapping

from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

KEY = "scheduler.capacity_limits"
NAMES = ("cpu", "memory")


def _limit(value: object) -> float | None:
    """`value` when it is a number above zero and at most a hundred percent, else None."""
    if isinstance(value, bool) or not isinstance(value, int | float) or math.isnan(value):
        return None
    return value if 0 < value <= 100 else None


class CapacityLimitSetting:
    """Each of cpu and memory's limit in the store, or none: a dimension with none, or one that cannot be read, keeps the
    config limit."""

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def _stored(self) -> dict[str, object]:
        raw = self.log.setting(KEY)
        return raw if isinstance(raw, dict) else {}

    def get(self, name: str) -> float | None:
        try:
            return _limit(self._stored().get(name))
        except Exception as exc:  # an unreadable limit is no override; the config limit still holds
            logger.warning("StarPulse scheduler: reading the capacity limits failed: %s", exc)
            return None

    def set(self, changes: Mapping[str, object]) -> None:
        """Keep each `changes` value as that dimension's limit, or with None clear it; a dimension left out stays. A name
        but cpu or memory, or a value but a number above zero and at most 100, raises ValueError and changes nothing."""
        for name, value in changes.items():
            if name not in NAMES:
                raise ValueError(f"{name} has no limit to set; only {' and '.join(NAMES)} do")
            if value is not None and _limit(value) is None:
                raise ValueError(f"{name} limit must be a percent above 0 and at most 100; got {value!r}")
        kept = {name: self.get(name) for name in NAMES}
        merged = {name: changes[name] if name in changes else kept[name] for name in NAMES}
        limits = {name: value for name, value in merged.items() if value is not None}
        if limits:
            self.log.set_setting(KEY, limits)
        else:
            self.log.delete_setting(KEY)
