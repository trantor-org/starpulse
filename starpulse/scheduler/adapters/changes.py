"""Follow the read model for the Scheduler's change deltas: the task and move events its loop wakes on, without folding a board."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import EventLog


class _Feed(Protocol):
    def follow_read_model(self) -> int: ...


class _Moves(Protocol):
    def publish_changes(self) -> int: ...


def follow_changes(feed: _Feed, moves: _Moves, stop: StopEvent, log: EventLog) -> threading.Thread:
    """Run `feed.follow_read_model` and `moves.publish_changes` on each wake of `log` on a daemon thread until `stop`; a
    pass that raises is logged and run again."""

    def pass_() -> None:
        feed.follow_read_model()
        moves.publish_changes()

    thread = threading.Thread(
        target=log.run_on_wake,
        args=(stop, pass_, "scheduler: the change poll failed"),
        name="scheduler-changes",
        daemon=True,
    )
    thread.start()
    return thread
