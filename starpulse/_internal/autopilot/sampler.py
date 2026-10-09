"""The capacity sampler: each period it reads the four capacity dimensions and says when one crosses its limit.

A dimension's headroom is its limit less its use; it is full once use reaches the limit. The sampler is the autopilot's
event source for resource changes, not a dispatch timer: `on_crossing` hears a dimension going full and going free
again, and the first sample is a baseline that says nothing.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from starpulse._internal.config.autopilot import DIMENSIONS

logger = logging.getLogger(__name__)

#: How often the server samples, in seconds.
PERIOD = 60.0


@dataclass(frozen=True)
class Reading:
    """One dimension's use against its limit: percent for `cpu` and `memory`, a count for `sessions`, points for `review`."""

    name: str
    use: float
    limit: float

    @property
    def full(self) -> bool:
        return self.use >= self.limit


@dataclass(frozen=True)
class Crossing:
    """A dimension that went full (`full`) or went free again since the sample before."""

    dimension: str
    use: float
    limit: float
    full: bool


class Sampler:
    """Samples `probe` (CPU and memory percent), `sessions` (autopilot sessions in flight) and `review` (review-lane
    points) against `limits`, and tells `on_crossing` each dimension whose fullness changed.

    `sample` runs on the sampler's thread and `readings` on the server's, so the latest pass is swapped in whole.
    """

    def __init__(
        self,
        limits: Mapping[str, float],
        probe: Callable[[], Mapping[str, float]],
        sessions: Callable[[], float],
        review: Callable[[], float],
        on_crossing: Callable[[Crossing], object],
        clock: Callable[[], float],
    ) -> None:
        self._limits = limits
        self._probe = probe
        self._uses = {"sessions": sessions, "review": review}
        self._on_crossing = on_crossing
        self._clock = clock
        self._latest: tuple[list[Reading], float | None] = ([], None)

    def readings(self) -> tuple[list[Reading], float | None]:
        """The latest pass in `DIMENSIONS` order and when it was taken; nothing, and no time, before the first sample."""
        return self._latest

    def sample(self) -> None:
        """Read every dimension once; a probe that fails keeps the readings of the pass before."""
        try:
            host = self._probe()
            use = {"cpu": host["cpu"], "memory": host["memory"]} | {name: read() for name, read in self._uses.items()}
            now = [Reading(name, use[name], self._limits[name]) for name in DIMENSIONS]
        except Exception:  # a probe is third-party code; the next period goes again
            logger.exception("StarPulse: the autopilot cannot sample capacity")
            return
        before = {reading.name: reading.full for reading in self._latest[0]}
        self._latest = (now, self._clock())
        for reading in now:
            if before.get(reading.name, reading.full) != reading.full:
                try:
                    self._on_crossing(Crossing(reading.name, reading.use, reading.limit, reading.full))
                except Exception:  # a listener's bug must not stop the sampler or hide the next crossing
                    logger.exception("StarPulse: an autopilot capacity listener failed")

    def run_forever(self, stop: threading.Event, interval: float = PERIOD) -> None:
        """Sample now and then every `interval` seconds until `stop` is set."""
        self.sample()
        while not stop.wait(interval):
            self.sample()
