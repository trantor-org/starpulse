"""Garbage collection on a timer, and the pause each collection costs, as Prometheus metrics.

On a free-threaded build a collection stops every thread, and under CPU contention the stop waits for descheduled
threads: an automatic collection mid-request stalls the whole worker for tens of milliseconds to seconds, which is the
`/api/task/{id}` p95 tail. A worker therefore turns automatic collection off and collects on a timer.
"""

import gc
import threading
import time
from typing import Any

#: Between two timed collections. Cyclic garbage waits at most this long; one pause of a few seconds in this span
#: reaches about 1% of requests.
COLLECT_EVERY_S = 300.0


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


def install(
    stop: threading.Event, interval_s: float = COLLECT_EVERY_S, pauses: GcPauses = PAUSES
) -> threading.Thread:
    """Turn automatic collection off, time every collection into `pauses`, and collect each `interval_s` until `stop`."""
    gc.callbacks.append(pauses.callback)
    gc.disable()

    def collect_each_interval() -> None:
        while not stop.wait(interval_s):
            gc.collect()

    timer = threading.Thread(target=collect_each_interval, name="gc-collect", daemon=True)
    timer.start()
    return timer
