"""Keep the Task read model folded and tell the page of each Task that changed."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import EventLog

__all__ = ["follow"]


class _Projector(Protocol):
    def catch_up(self, *, index: bool = True) -> int: ...

    def index(self) -> None: ...


class _Feed(Protocol):
    def follow_read_model(self) -> int: ...


def follow(projector: _Projector | None, feed: _Feed, stop: StopEvent, log: EventLog) -> threading.Thread:
    """Run `projector.catch_up` (none: another process folds) and then `feed.follow_read_model` on each wake of `log`
    until `stop`, then index the folded rows for search, so the page never waits on the index; a pass that raises is
    logged and run again."""

    def fold() -> None:
        if projector is not None:
            projector.catch_up(index=False)
        feed.follow_read_model()
        if projector is not None:
            projector.index()

    thread = threading.Thread(
        target=log.run_on_wake,
        args=(stop, fold, "StarPulse: the read model pass failed"),
        name="read-model-follow",
        daemon=True,
    )
    thread.start()
    return thread
