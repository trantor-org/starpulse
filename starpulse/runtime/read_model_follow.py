"""Keep the Task read model folded and tell the page of each Task that changed."""

import threading
from typing import TYPE_CHECKING, Protocol

from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import EventLog

__all__ = ["follow"]


class _Projector(Protocol):
    def fold_tasks(self) -> int: ...

    def fold_machines(self) -> None: ...

    def index(self) -> None: ...


class _Feed(Protocol):
    def follow_read_model(self) -> int: ...


def follow(projector: _Projector | None, feed: _Feed, stop: StopEvent, log: EventLog) -> threading.Thread:
    """Run `projector.fold_tasks` (none: another process folds) on each wake of `log` until `stop`, on a thread of its
    own so a new Task's row waits for no other fold. The returned thread folds the machines, runs
    `feed.follow_read_model` and then indexes the folded rows for search, so the page never waits on the index. A pass
    that raises is logged and run again."""

    def fold() -> None:
        if projector is not None:
            projector.fold_machines()
        feed.follow_read_model()
        if projector is not None:
            projector.index()

    if projector is not None:
        threading.Thread(
            target=log.run_on_wake,
            args=(stop, projector.fold_tasks, "StarPulse: the task fold pass failed"),
            name="task-fold",
            daemon=True,
        ).start()
    thread = threading.Thread(
        target=log.run_on_wake,
        args=(stop, fold, "StarPulse: the read model pass failed"),
        name="read-model-follow",
        daemon=True,
    )
    thread.start()
    return thread
