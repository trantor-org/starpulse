"""The built-in host probe: CPU and memory use in percent, read through psutil, so a fresh install needs no monitoring stack.

A probe is any zero-argument callable that answers `{"cpu": percent, "memory": percent}`; the sampler takes another in its place.
"""

import time
from collections import deque
from collections.abc import Callable

import psutil

WINDOW = 60.0  # seconds of host ticks one CPU reading averages, so a momentary spike does not read as a saturated host


def _ticks() -> tuple[float, float]:
    """The host's busy and total CPU ticks since boot, as `psutil.cpu_percent` counts them."""
    times = psutil.cpu_times()
    idle = times.idle + getattr(times, "iowait", 0.0)
    total = sum(times) - getattr(times, "guest", 0.0) - getattr(times, "guest_nice", 0.0)
    return total - idle, total


class LocalProbe:
    """Reads the host's CPU and memory with psutil.

    CPU is the busy share of the ticks over the last `WINDOW` seconds, or since construction while the probe is younger.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._marks = deque([(clock(), *_ticks())])
        self._cpu = 0.0

    def __call__(self) -> dict[str, float]:
        now = self._clock()
        busy, total = _ticks()
        self._marks.append((now, busy, total))
        while len(self._marks) > 2 and self._marks[1][0] <= now - WINDOW:  # keep the newest mark at or before the window's start
            self._marks.popleft()
        _, base_busy, base_total = self._marks[0]
        if total > base_total:
            self._cpu = min(100.0, max(0.0, 100.0 * (busy - base_busy) / (total - base_total)))  # a tick counter can step back
        return {"cpu": self._cpu, "memory": psutil.virtual_memory().percent}
