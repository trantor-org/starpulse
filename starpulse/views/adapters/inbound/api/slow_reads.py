"""The `slow_read` line a timed read route logs when a read takes long."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from starpulse.views.adapters.inbound.api.neutral import Arrival

logger = logging.getLogger(__name__)


class SlowReads:
    """Logs each read of `route` that took `threshold_s` seconds or more from accept to the last byte written, with the
    seconds it waited for a handler thread, computed its answer and wrote it, the reads in flight when it began, and
    the request workers busy and streams open when it was accepted, so a stall of the whole process can be told apart by
    the phase, and the occupant of the pool, that held the time."""

    class _Read:
        def __init__(self) -> None:
            self.ran_at: float | None = None
            self.computed_at: float | None = None

        def ran(self) -> None:
            self.ran_at = time.monotonic()

        def computed(self) -> None:
            self.computed_at = time.monotonic()

    def __init__(self, route: str, threshold_s: float) -> None:
        self._route = route
        self._threshold_s = threshold_s
        self._lock = threading.Lock()
        self._in_flight = 0

    @contextmanager
    def watch(self, query: str, arrival: Arrival) -> Iterator[_Read]:
        with self._lock:
            self._in_flight += 1
            in_flight = self._in_flight
        read = self._Read()
        try:
            yield read
        finally:  # a write that fails on a closed socket is the slow read most worth the line
            ended = time.monotonic()
            with self._lock:
                self._in_flight -= 1
            ran_at = read.ran_at if read.ran_at is not None else ended
            computed_at = read.computed_at if read.computed_at is not None else ended
            queued_s, compute_s, write_s = ran_at - arrival.at, computed_at - ran_at, ended - computed_at
            if queued_s + compute_s + write_s >= self._threshold_s:
                logger.warning(
                    "slow_read route=%s query=%s queue_s=%.3f compute_s=%.3f write_s=%.3f in_flight=%d"
                    " busy=%d streams=%d",
                    self._route,
                    query,
                    queued_s,
                    compute_s,
                    write_s,
                    in_flight,
                    arrival.busy,
                    arrival.streams,
                )
