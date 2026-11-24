"""The pause each garbage collection costs, as Prometheus metrics; collection itself is Python's own."""

import gc
import threading
import time
from typing import Any


FULL_COLLECTION_EVERY = 50_000
"""Middle-generation collections between full-heap ones: about a day at the live worker's 30 a minute."""


def bound_full_collections() -> None:
    """Make the full-heap collection rare: each stalled every request for 0.4-3.8 s and freed about 850 objects."""
    young, middle, _ = gc.get_threshold()
    gc.set_threshold(young, middle, FULL_COLLECTION_EVERY)


class GcPauses:
    """Collections counted, objects they freed, and the seconds all stopped threads waited, as `starpulse_gc_*`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = threading.local()
        self._collections = 0
        self._collected = 0
        self._sum_s = 0.0
        self._max_s = 0.0

    def callback(self, phase: str, info: dict[str, Any]) -> None:
        """The `gc.callbacks` entry: time from a collection's `start` to its `stop` on the thread that ran it."""
        if phase == "start":
            self._started.at = time.perf_counter()
            return
        pause_s = time.perf_counter() - getattr(self._started, "at", time.perf_counter())
        with self._lock:
            self._collections += 1
            self._collected += info.get("collected", 0)
            self._sum_s += pause_s
            self._max_s = max(self._max_s, pause_s)

    def exposition(self) -> str:
        with self._lock:
            rows = [
                ("starpulse_gc_collections_total", "counter", self._collections),
                ("starpulse_gc_collected_total", "counter", self._collected),
                ("starpulse_gc_pause_seconds_sum", "counter", self._sum_s),
                ("starpulse_gc_pause_seconds_max", "gauge", self._max_s),
            ]
        return "".join(f"# TYPE {name} {kind}\n{name} {value}\n" for name, kind, value in rows)


PAUSES = GcPauses()

