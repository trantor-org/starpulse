"""The task:ratings stream contract: one entry per change of a task's pass/fail rating.

A change is `pass`, `fail` (with an optional one-line `reason`) or `cleared`; the latest entry of a task is its rating and
every entry is kept for analytics. An entry carries `task`, `verdict`, `time` (epoch seconds of the change), `actor`
and the `session` and `harness` the write named, and `reason` when given. `Ratings` folds the stream to each task's
latest entry with its change count, and refolds only when the stream has grown.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

STREAM = "task:ratings"

logger = logging.getLogger(__name__)


def change(
    task: str, verdict: str, reason: str, at: float, actor: str = "", session: str = "", harness: str = ""
) -> dict[str, Any]:
    """The fields of a rating entry: the task, the verdict, the time and the writer, each optional one only when given."""
    named = {"reason": reason, "session": session, "harness": harness}
    return {"task": task, "verdict": verdict, "time": at, "actor": actor, **{k: v for k, v in named.items() if v}}


def append(log: EventLog, fields: dict[str, Any]) -> int | None:
    """Append a rating entry to `log`, fail-open: the cursor, or None when it was not appended."""
    return log._append(STREAM, fields)


def _rating(entry: Entry, changes: int) -> dict[str, Any]:
    return {
        "verdict": entry.fields["verdict"],
        "reason": entry.fields.get("reason", ""),
        "at": entry.fields["time"],
        "changes": changes,
    }


class Ratings:
    """The rating of each task the stream holds, its latest entry and change count."""

    def __init__(self, log: EventLog) -> None:
        self._log = log
        self._lock = threading.Lock()
        self._cursor: int | None = None
        self._latest: dict[str, dict[str, Any]] = {}

    def latest(self) -> dict[str, dict[str, Any]]:
        """Each rated task's latest rating; the last one folded when the database cannot be read."""
        with self._lock:
            try:
                cursor = self._log.last(STREAM)
                if cursor != self._cursor:
                    self._latest = self._fold()
                    self._cursor = cursor
            except Exception as exc:  # fail open: a snapshot never fails on the rating stream
                logger.warning("Ratings: reading %s failed (showing the last ratings): %s", STREAM, exc)
            return dict(self._latest)

    def rate(self, fields: dict[str, Any]) -> dict[str, Any] | None:
        """Append `fields` as a change and return the task's rating now, or None when the change was not appended."""
        if append(self._log, fields) is None:
            return None
        return self.latest().get(fields["task"])

    def _fold(self) -> dict[str, dict[str, Any]]:
        from starpulse.event_log.event_log import Tail  # deferred: event_log loads the database stack

        ratings: dict[str, dict[str, Any]] = {}

        def fold(entry: Entry) -> None:
            task = entry.fields["task"]
            changes = ratings.get(task, {}).get("changes", 0) + 1
            ratings[task] = _rating(entry, changes)

        Tail.replay(self._log, STREAM).catch_up(fold)
        return ratings
