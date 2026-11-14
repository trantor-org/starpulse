"""The capacity sampler: on each pass it reads the four capacity dimensions and says when one crosses its limit.

A dimension's headroom is its limit less its use; it is full once use reaches the limit. The sampler is the scheduler's
event source for resource changes, woken by a pressure trigger or a capacity event, not a dispatch timer: `on_crossing`
hears a dimension going full and going free again, and the first sample is a baseline that says nothing.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass

from starpulse.event_log.wake import StopEvent
from starpulse.scheduler.model.config import DIMENSIONS

logger = logging.getLogger(__name__)


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
    """Samples `probe` (CPU and memory percent), `sessions` (scheduler sessions in flight) and `review` (review-lane
    points) against `limits`, and tells `on_crossing` each dimension whose fullness changed.

    `limits` is read on every sample and every `readings`, so a limit an operator changes counts at once. `sample` runs
    on the sampler's thread and `readings` on the server's, so the latest pass is swapped in whole.
    """

    def __init__(
        self,
        limits: Callable[[], Mapping[str, float]],
        probe: Callable[[], Mapping[str, float]],
        sessions: Callable[[], float],
        review: Callable[[], float],
        on_crossing: Callable[[Crossing], object],
        clock: Callable[[], float],
        remember: Callable[[list[Reading], float], object] | None = None,
        hold: Callable[[], AbstractContextManager[object]] = nullcontext,
    ) -> None:
        self._limits = limits
        self._probe = probe
        self._uses = {"sessions": sessions, "review": review}
        self._on_crossing = on_crossing
        self._clock = clock
        self._remember = remember
        self._hold = hold
        self._latest: tuple[list[Reading], float | None] = ([], None)

    def restore(self, readings: list[Reading], at: float) -> None:
        """Install a sample saved from a previous process; the next `sample` treats it as the baseline."""
        self._latest = (readings, at)

    def readings(self) -> tuple[list[Reading], float | None]:
        """The latest pass in `DIMENSIONS` order, each judged against its limit as it is now, and when it was taken;
        nothing, and no time, before the first sample."""
        readings, at = self._latest
        limits = self._limits()
        return [Reading(r.name, r.use, limits.get(r.name, r.limit)) for r in readings], at

    def sample(self) -> None:
        """Read every dimension once; a probe that fails keeps the readings of the pass before."""
        try:
            host = self._probe()
            with self._hold():  # the sessions and review reads share one build of the board's open tasks
                reads = {name: read() for name, read in self._uses.items()}
            use = {"cpu": host["cpu"], "memory": host["memory"]} | reads
            limits = self._limits()
            now = [Reading(name, use[name], limits[name]) for name in DIMENSIONS]
        except Exception:  # a probe is third-party code; the next period goes again
            logger.exception("StarPulse: the scheduler cannot sample capacity")
            return
        before = {reading.name: reading.full for reading in self._latest[0]}
        taken = self._clock()
        self._latest = (now, taken)
        if self._remember is not None:
            try:
                self._remember(now, taken)
            except Exception:  # a store that cannot be written must not stop sampling
                logger.exception("StarPulse: cannot keep the scheduler capacity sample")
        for reading in now:
            if before.get(reading.name, reading.full) != reading.full:
                try:
                    self._on_crossing(Crossing(reading.name, reading.use, reading.limit, reading.full))
                except Exception:  # a listener's bug must not stop the sampler or hide the next crossing
                    logger.exception("StarPulse: a scheduler capacity listener failed")

    def run_forever(self, stop: StopEvent, wake: threading.Event) -> None:
        """Sample now, then once each time `wake` is set (a pressure trigger fired) until `stop` is set; never on a timer."""
        stop.listen(wake.set)
        try:
            self.sample()
            while not stop.is_set():
                wake.wait()
                wake.clear()
                if not stop.is_set():
                    self.sample()
        finally:
            stop.unlisten(wake.set)
