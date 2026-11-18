"""Garbage collection after a count of served requests, and the pause each collection costs, as Prometheus metrics.

On a free-threaded build a collection stops every thread, and under CPU contention the stop waits for descheduled
threads: an automatic collection mid-request stalls the whole worker for tens of milliseconds to seconds, which is the
`/api/task/{id}` p95 tail. A worker therefore turns automatic collection off and collects after a count of requests,
on a thread of its own, so a request never waits for the collection it paid for.

The first collection also freezes what survives it, so later ones scan only what the worker allocated since: a pass
over the whole multi-gigabyte heap stalled every thread for 2-3 s. A cycle that dies after the freeze is not
collected until the worker is replaced, which `--hours` bounds.
"""

import ctypes
import gc
import threading
import time
from collections.abc import Callable
from typing import Any

from starpulse.event_log.wake import StopEvent

#: Requests served between two collections. A worker that serves none allocates nothing to collect; one that serves
#: them leaves cyclic garbage for at most this many.
COLLECT_EVERY_REQUESTS = 2000


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


def release_native_heap() -> None:
    """Hand glibc's freed arena pages back to the kernel (`malloc_trim`); a no-op where glibc is absent.

    The free-threaded build's objects live in mimalloc, which `MIMALLOC_PURGE_DELAY=0` already purges; what this
    reclaims is the 50-75 MB of freed native allocations (SQLite, OpenSSL, buffers) the worker would otherwise keep.
    """
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        return


class Collector:
    """Counts served requests and wakes a thread that collects and trims after each `every`."""

    def __init__(self, every: int, trim: Callable[[], None]) -> None:
        self._every = every
        self._trim = trim
        self._lock = threading.Lock()
        self._count = 0
        self._due = threading.Event()

    def served(self) -> None:
        with self._lock:
            self._count += 1
            if self._count < self._every:
                return
            self._count = 0
        self._due.set()

    def run(self, stop: StopEvent) -> None:
        stop.listen(self._due.set)
        frozen = False
        try:
            while self._due.wait() and not stop.is_set():
                self._due.clear()
                gc.collect()
                if not frozen:
                    gc.freeze()  # what lives after the first collection is the loaded heap; a full pass over it took 2-3 s
                    frozen = True
                self._trim()
        finally:
            stop.unlisten(self._due.set)


def install(
    stop: StopEvent,
    every: int = COLLECT_EVERY_REQUESTS,
    pauses: GcPauses = PAUSES,
    trim: Callable[[], None] = release_native_heap,
) -> Collector:
    """Turn automatic collection off, time every collection into `pauses`, and collect then `trim` after each `every`
    requests the returned collector counts (`served`) until `stop`."""
    gc.callbacks.append(pauses.callback)
    gc.disable()
    collector = Collector(every, trim)
    threading.Thread(target=collector.run, args=(stop,), name="gc-collect", daemon=True).start()
    return collector
