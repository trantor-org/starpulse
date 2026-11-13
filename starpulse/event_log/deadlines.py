"""Keyed one-shot deadlines: a thread sleeps until the nearest one and calls back once, so a timed release is an event."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from starpulse.event_log.wake import StopEvent

logger = logging.getLogger(__name__)


class Deadlines:
    """One deadline per key. The events that move a deadline `arm` it again or `cancel` it; a fired key is forgotten,
    except one whose callback raised, which fires again `retry` seconds later unless the callback armed it itself."""

    def __init__(
        self, fire: Callable[[str], None], *, clock: Callable[[], float] = time.time, retry: float = 60.0
    ) -> None:
        self._fire = fire
        self._clock = clock
        self._retry = retry
        self._due: dict[str, float] = {}
        self._changed = threading.Condition()

    def arm(self, key: str, at: float) -> None:
        """Fire `key` at wall-clock `at`, replacing any deadline it has."""
        with self._changed:
            self._due[key] = at
            self._changed.notify()

    def cancel(self, key: str) -> None:
        with self._changed:
            self._due.pop(key, None)
            self._changed.notify()

    def start(self, stop: StopEvent, *, thread_name: str) -> threading.Thread:
        """Run the timer on a thread until `stop`."""

        def wake() -> None:
            with self._changed:
                self._changed.notify_all()

        stop.listen(wake)
        thread = threading.Thread(target=self._run, args=(stop,), name=thread_name, daemon=True)
        thread.start()
        return thread

    def _run(self, stop: StopEvent) -> None:
        while not stop.is_set():
            for key in self._take_due(stop):
                try:
                    self._fire(key)
                except Exception:  # one key must not end the timer, nor lose its deadline
                    logger.exception("deadlines: cannot fire %s", key)
                    with self._changed:
                        self._due.setdefault(key, self._clock() + self._retry)

    def _take_due(self, stop: StopEvent) -> list[str]:
        """The keys now due, removed; sleeps until the nearest deadline, an arm, a cancel or `stop`."""
        with self._changed:
            now = self._clock()
            due = [key for key, at in self._due.items() if at <= now]
            for key in due:
                del self._due[key]
            if not due and not stop.is_set():
                self._changed.wait(max(0.0, min(self._due.values()) - now) if self._due else None)
            return due
