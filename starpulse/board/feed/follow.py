"""Following a board's event stream into the feed, and the resume and run hooks around it."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from starpulse.board.feed.shared import BoardStore, logger
from starpulse.event_log.polling import DEFAULT_POLL_INTERVAL

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog


class InstanceRuns:
    """The feed as one runs adapter instance sees it: it publishes its workflows and errors under its own name."""

    def __init__(self, feed: BoardFeed, instance: str) -> None:
        self._feed = feed
        self._instance = instance

    @property
    def tied(self) -> frozenset[str]:
        """The workflows of this instance a Board event cues or that write one, whose recent runs the adapter reports."""
        return self._feed.tied(self._instance)

    def set_dags(
        self,
        dags: list | None,
        error: str | None,
        pools: list | None = None,
        startable: list[str] | None = None,
        cpu: dict | None = None,
    ) -> None:
        self._feed.set_dags(self._instance, dags, error, pools, startable, cpu)


class Followed(Protocol):
    """What `follow` needs of a feed: to be told the stream is not reached yet and where it ends."""

    def await_stream(self) -> None: ...

    def expect(self, last_id: str) -> None: ...


@runtime_checkable
class Resumable(Protocol):
    """A feed that keeps its state across restarts (`BoardFeed`), so a reader of its stream resumes after a cursor."""

    def resume(self, store: BoardStore, stream: str, retained: Callable[[int], bool]) -> int | None: ...

    def keep_saved(self, stop: threading.Event, interval: float = ...) -> None: ...


def retained(log: EventLog, stream: str) -> Callable[[int], bool]:
    """Whether the log still holds every `stream` row after a saved position: `Tail`'s gap rule, and a position the
    log has not reached yet (the database was replaced) is no position of this log."""

    def retained(after: int) -> bool:
        oldest = log.oldest()
        return oldest is not None and oldest - 1 <= after <= (log.last(stream) or 0)

    return retained


def follow(
    feed: Followed,
    log: EventLog,
    stream: str,
    handle: Callable[[str, dict], None],
    *,
    stop: threading.Event | None = None,
    interval: float = DEFAULT_POLL_INTERVAL,
) -> threading.Thread:
    """Read `stream` of the event log into `feed` through `handle(entry_id, fields)` on a daemon thread and return it.

    A feed that keeps its state (`Resumable`) restores the Board the last run saved in the log and reads only the
    entries after the cursor it reflects, then keeps saving it until `stop`. With no saved Board, or one the log no
    longer covers, the feed replays from the oldest entry the log retains: hourly reconciles keep the latest state
    of every task inside the retention. The feed turns ready once the newest entry `stream` held when it started
    has been read. While the database cannot be reached the feed is not ready and the start retries every
    `interval`; a later outage is `Tail.run`'s to retry. `stop` ends the reader.
    """
    feed.await_stream()
    stop = stop or threading.Event()

    def run() -> None:
        after = None
        while not stop.is_set():
            try:
                last = log.last(stream)
                if isinstance(feed, Resumable):
                    after = feed.resume(log.checkpoints, stream, retained(log, stream))
                break
            except Exception as exc:  # the database is unreachable; the next attempt retries
                logger.warning("StarPulse: cannot reach the event log for %s, retrying: %s", stream, exc)
                stop.wait(interval)
        else:
            return
        feed.expect(str(last or 0))
        if isinstance(feed, Resumable):
            threading.Thread(target=feed.keep_saved, args=(stop,), name="board-state", daemon=True).start()
        # no cursor replays the whole retention

        tail = log.tail(stream, after=after, interval=interval)
        tail.run(lambda entry: handle(str(entry.id), entry.fields), stop)

    thread = threading.Thread(target=run, name="board-feed", daemon=True)
    thread.start()
    return thread


def _ledger_changes(sent: Mapping[str, Sequence[dict]], now: Mapping[str, Sequence[dict]]) -> dict[str, list[dict]]:
    """Per event, the rows of `now` that differ from the same key in `sent` (or are new). A row that left the page is
    not named: a page that holds it keeps it."""
    changed: dict[str, list[dict]] = {}
    for event, rows in now.items():
        before = {row["key"]: row for row in sent.get(event, ())}
        if found := [row for row in rows if before.get(row["key"]) != row]:
            changed[event] = found
    return changed
