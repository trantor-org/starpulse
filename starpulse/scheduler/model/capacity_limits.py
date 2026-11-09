"""The cpu and memory limits an operator sets from StarPulse Admin: kept in the history store, they override the
`[scheduler.limits]` in `starpulse.toml` until cleared. The sampler reads them on every reading, so a change needs no
restart."""

import math
from collections.abc import Mapping

from starpulse.event_log.event_log import EventLog
from starpulse.scheduler.model.override_store import OverrideStore

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
        self.store = OverrideStore(log, KEY, _limit)

    def get(self, name: str) -> float | None:
        return _limit(self.store.get(name))

    def set(self, changes: Mapping[str, object]) -> None:
        """Keep each `changes` value as that dimension's limit, or with None clear it; a dimension left out stays. A name
        but cpu or memory, or a value but a number above zero and at most 100, raises ValueError and changes nothing."""
        for name, value in changes.items():
            if name not in NAMES:
                raise ValueError(f"{name} has no limit to set; only {' and '.join(NAMES)} do")
            if value is not None and _limit(value) is None:
                raise ValueError(f"{name} limit must be a percent above 0 and at most 100; got {value!r}")
        merged = {**self.store.all(), **changes}
        self.store.save({name: value for name, value in merged.items() if value is not None})

