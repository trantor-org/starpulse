"""What other processes keep in the log, applied when a request reads it, so the process that serves requests runs no follower thread.

A step runs when the log's commit count has moved since the last read, so a read with nothing committed in between costs
none of the queries a follower's wake would; a read after a write sees the write. Reads that wait on a running apply
share the one that follows it: an apply that began after a read arrived is as fresh as the one that read would run.
"""

import logging
import threading
from collections.abc import Callable

from starpulse.event_log.event_log import Entry, EventLog

logger = logging.getLogger(__name__)


class CaughtUp:
    def __init__(self, log: EventLog) -> None:
        self._log = log
        self._steps: list[Callable[[], None]] = []
        self._every: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._commits: int | None = None
        self._begun = 0  # applies begun so far
        self._landed = 0  # the number of the last apply that finished every step

    def state(self, name: str, apply: Callable[[], None]) -> None:
        """Apply the state kept under `name` now, and again at the first read after its version moves."""
        seen: int | None = self._log.version(name)  # before the first apply, so a write between the two is applied by the next read
        try:
            apply()
        except Exception:
            logger.warning("EventLog: %s could not be applied at start", name, exc_info=True)
            seen = None

        def step() -> None:
            nonlocal seen
            if (version := self._log.version(name)) != seen:
                apply()
                seen = version  # after the apply, so one that raised is tried again by the next read

        self._steps.append(step)

    def entries(self, stream: str, handle: Callable[[Entry], None], after: int) -> None:
        """Pass `handle` each entry of `stream` past `after`, at the first read after it is appended."""
        tail = self._log.tail(stream, after=after)
        pending: list[
            Entry
        ] = []  # the tail's cursor has passed these, so one `handle` raised on is kept for the next read

        def step() -> None:
            tail.catch_up(pending.append)
            while pending:
                handle(pending[0])
                pending.pop(0)

        self._steps.append(step)

    def every_read(self, step: Callable[[], None]) -> None:
        """Run `step` at each read, for a fact the log never announces, such as a process that has exited."""
        self._every.append(step)

    def due(self) -> bool:
        """Whether a read has something to apply: a commit since the last one, or a step that runs at every read."""
        return bool(self._every) or self._log.appends != self._commits

    def __call__(self) -> None:
        arrived = self._begun  # before the lock: an apply numbered past it began after this read arrived
        with self._lock:  # a read and its apply finish before the next starts, so an old read never lands last
            commits = self._log.appends  # before the steps, so a commit during them is read by the next call
            if commits != self._commits and self._landed <= arrived:
                self._begun += 1
                try:
                    for step in self._steps:
                        step()
                    self._commits = commits
                    self._landed = self._begun
                except Exception:  # the log is down: the next read tries again, with what the feed held until then
                    logger.warning("EventLog: a request could not read what the workers keep", exc_info=True)
            for step in self._every:
                step()
