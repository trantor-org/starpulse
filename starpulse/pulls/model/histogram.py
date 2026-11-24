"""Seconds observed from any thread as a Prometheus histogram, and the timing of a store's writes by phase."""

import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

__all__ = ["Histogram", "Timings"]

#: Buckets for a write that takes milliseconds when the store is idle and seconds when the host is loaded.
WRITE_BUCKETS_S = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


class Histogram:
    """Seconds observed from any thread, as the cumulative buckets of a Prometheus histogram."""

    def __init__(self, bounds: Sequence[float]) -> None:
        self._bounds = bounds
        self._lock = threading.Lock()
        self._counts = [0] * (len(bounds) + 1)
        self._sum = 0.0

    def observe(self, seconds: float) -> None:
        at = next((i for i, bound in enumerate(self._bounds) if seconds <= bound), len(self._bounds))
        with self._lock:
            for i in range(at, len(self._counts)):
                self._counts[i] += 1
            self._sum += seconds

    def lines(self, name: str, help_text: str) -> list[str]:
        return [f"# HELP {name} {help_text}", f"# TYPE {name} histogram", *self.samples(name)]

    def samples(self, name: str, labels: str = "") -> list[str]:
        """The histogram's sample lines, each carrying `labels` (`lane="ready",hook="false"`) when given."""
        with self._lock:
            counts, total = list(self._counts), self._sum
        head, tail = (f"{labels},", f"{{{labels}}}") if labels else ("", "")
        buckets = [
            f'{name}_bucket{{{head}le="{bound:g}"}} {count}' for bound, count in zip(self._bounds, counts, strict=False)
        ]
        return [
            *buckets,
            f'{name}_bucket{{{head}le="+Inf"}} {counts[-1]}',
            f"{name}_sum{tail} {total:g}",
            f"{name}_count{tail} {counts[-1]}",
        ]


class Timings:
    """One histogram of seconds per phase, under one metric name with a `phase` label."""

    def __init__(self, name: str, help_text: str, phases: Sequence[str], bounds: Sequence[float] = WRITE_BUCKETS_S) -> None:
        self._name = name
        self._help = help_text
        self._phases = {phase: Histogram(bounds) for phase in phases}

    @contextmanager
    def time(self, phase: str) -> Iterator[None]:
        """Observe the seconds the block takes in `phase`, however it ends."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self._phases[phase].observe(time.perf_counter() - start)

    def exposition(self) -> str:
        lines = [f"# HELP {self._name} {self._help}", f"# TYPE {self._name} histogram"]
        for phase, histogram in self._phases.items():
            lines += histogram.samples(self._name, f'phase="{phase}"')
        return "\n".join(lines) + "\n"
