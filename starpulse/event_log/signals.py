"""The statements a follower reads its wake from: one watched value per distinct statement, shared by every follower of it.

The commit watch evaluates each statement after a commit by another connection, so a follower wakes when what it reads
moved, never on a commit that moved something else (its own checkpoint included)."""

import sqlite3
import threading
from collections.abc import Callable
from typing import Any

from starpulse.event_log.tables import events, settings
from starpulse.event_log.wake import StopEvent

def read_value(connection: sqlite3.Connection, sql: str) -> Any:
    """What `sql` returns, or None while a table it names does not exist yet."""
    try:
        return connection.execute(sql).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise


class Signals:
    def __init__(self) -> None:
        self._moved = threading.Condition()
        #: Each statement with its last value and the number of times that value moved.
        self._watched: dict[str, list[Any]] = {}

    def version(self, sql: str, first: Callable[[str], Any]) -> int:
        """How many times the value of `sql` moved, the `seen` for `wait`; `first` reads its value when none watched it yet."""
        with self._moved:
            if (watched := self._watched.get(sql)) is not None:
                return watched[1]
        value = first(sql)
        with self._moved:
            return self._watched.setdefault(sql, [value, 0])[1]

    def wait(self, sql: str, seen: int, stop: StopEvent) -> None:
        """Return when the value of `sql` moved past `seen` or `stop` is set; no timer ends it."""
        stop.listen(self._notify)  # before the check below, so a stop between the check and the wait is not lost
        try:
            with self._moved:
                while self._watched[sql][1] == seen and not stop.is_set():
                    self._moved.wait()
        finally:
            stop.unlisten(self._notify)

    def probe(self, connection: sqlite3.Connection) -> None:
        """Read each watched statement and wake the followers of one whose value moved."""
        with self._moved:
            statements = list(self._watched)
        for sql in statements:
            value = read_value(connection, sql)
            with self._moved:
                if (watched := self._watched[sql])[0] != value:
                    watched[0] = value
                    watched[1] += 1
                    self._moved.notify_all()

    def reset(self) -> None:
        """Wake every follower, for a check that failed: a commit may have landed unseen."""
        with self._moved:
            for watched in self._watched.values():
                watched[1] += 1
            self._moved.notify_all()

    def _notify(self) -> None:
        with self._moved:
            self._moved.notify_all()


#: The newest event id: what a follower of the events table reads.
HEAD = f"SELECT max(id) FROM {events.name}"


def setting(key: str) -> str:
    """The value kept under settings `key`: what a follower of another process's revision reads."""
    return f"SELECT value FROM {settings.name} WHERE key = '{key}'"
