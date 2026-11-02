"""Poll the read model for the Scheduler's change deltas: the task and move events its loop wakes on, without folding a board."""

from __future__ import annotations

import logging
import threading
from typing import Protocol

logger = logging.getLogger(__name__)

#: Seconds between two polls of the read model.
POLL_S = 0.5


class _Feed(Protocol):
    def follow_read_model(self) -> int: ...


class _Moves(Protocol):
    def publish_changes(self) -> int: ...


def follow_changes(feed: _Feed, moves: _Moves, stop: threading.Event, interval_s: float = POLL_S) -> threading.Thread:
    """Run `feed.follow_read_model` and `moves.publish_changes` every `interval_s` on a daemon thread until `stop`; a pass
    that raises is logged and the next one runs."""

    def run() -> None:
        while not stop.is_set():
            try:
                feed.follow_read_model()
                moves.publish_changes()
            except Exception:
                logger.exception("scheduler: the change poll failed")
            stop.wait(interval_s)

    thread = threading.Thread(target=run, name="scheduler-changes", daemon=True)
    thread.start()
    return thread
