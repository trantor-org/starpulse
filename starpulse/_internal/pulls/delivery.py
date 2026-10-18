"""The Delivery context's seam with `serve`: the projection out, the refresh requests, actor notes and metrics across.

The Delivery worker (`starpulse worker pulls`) is the one writer of the pull store and the one reader of GitHub; `serve`
keeps the store read-only. What the worker projects, and what `serve` must say back to it, cross the event log:

- the worker keeps its latest projection in the `PROJECTION` setting and announces each change on `PROJECTED_STREAM`;
  `serve` applies it to its feed (`Projected`), so snapshots keep drawing pull request state;
- a page's refresh request lands on `REFRESH_STREAM` (`request_refresh`) and the worker asks `PullSync` for it;
- the task actor's lane attributions land on `NOTES_STREAM` so the serving feed names the actor on the lane move the
  board file's change produces (`NotingFeed`, `follow_notes`); the note is logged before the write, so a move placed
  before the follower read its note reads the stream itself first (`Notes.catch_up`);
- the actor's `/metrics` text is kept in the `METRICS` setting for `serve` to relay.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse._internal.eventlog.event_log import Entry, EventLog

logger = logging.getLogger(__name__)

PROJECTION = "pulls.projection"
METRICS = "pulls.metrics"
PROJECTED_STREAM = "pulls:projected"
REFRESH_STREAM = "pulls:refresh"
NOTES_STREAM = "pulls:notes"
#: Seconds between the worker's writes of its metrics.
METRICS_S = 15.0
#: Seconds an idle tail waits for an append from another process.
POLL_S = 1.0


def _follow(name: str, log: EventLog, stream: str, after: int, handle: Callable[[Entry], None], stop: threading.Event):
    from starpulse._internal.eventlog.event_log import Tail  # noqa: PLC0415 - the database stack loads when a log opens

    tail = Tail(log, stream, after=after, interval=POLL_S)
    thread = threading.Thread(target=tail.run, args=(handle, stop), name=name, daemon=True)
    thread.start()
    return thread


class Publisher:
    """Keeps the feed's pull request projection in the log, announcing each change."""

    def __init__(self, log: EventLog, feed: Any) -> None:
        self._log = log
        self._feed = feed
        self._last: dict | None = None

    def publish(self) -> None:
        """Write the feed's projection and announce it, unless the log already holds this one. A log that cannot be
        written is tried again on the next call."""
        body = {"pulls": self._feed.pulls(), "answers": self._feed.pull_answers()}
        if body == self._last:
            return
        try:
            self._log.set_setting(PROJECTION, body)
        except Exception:
            logger.warning("pulls: the projection was not kept", exc_info=True)
            return
        self._last = body
        self._log.append(PROJECTED_STREAM, {})


class Projected:
    """Applies the worker's kept projection to the serving feed."""

    def __init__(self, log: EventLog, feed: Any) -> None:
        self._log = log
        self._feed = feed

    def apply(self) -> None:
        """Take the kept projection; none kept yet, or one unreadable, leaves the feed as it was."""
        try:
            body = self._log.setting(PROJECTION)
        except Exception:
            logger.warning("pulls: the projection was not read", exc_info=True)
            return
        if isinstance(body, dict) and isinstance(body.get("pulls"), dict) and isinstance(body.get("answers"), dict):
            self._feed.set_pulls(body["pulls"], body["answers"])

    def follow(self, stop: threading.Event) -> threading.Thread:
        """Apply the kept projection now, then each one announced after, on a thread until `stop`."""
        after = self._log.head() or 0
        self.apply()
        return _follow("pull-projected", self._log, PROJECTED_STREAM, after, lambda _entry: self.apply(), stop)


def request_refresh(log: EventLog, tracked: Callable[[], list[str]]) -> Callable[[str, int], bool]:
    """A refresh request for `serve`'s page: queued for the worker when `repo` is tracked, refused (False) otherwise."""

    def request(repo: str, number: int) -> bool:
        if repo not in tracked():
            return False
        log.append(REFRESH_STREAM, {"repo": repo, "number": number})
        return True

    return request


def follow_refreshes(log: EventLog, request: Callable[[str, int], Any], stop: threading.Event) -> threading.Thread:
    """Hand each refresh asked from now on to `request` (the pull sync's), on a thread until `stop`."""

    def handle(entry: Entry) -> None:
        request(entry.fields["repo"], int(entry.fields["number"]))

    return _follow("pull-refresh", log, REFRESH_STREAM, log.head() or 0, handle, stop)


def follow_events(
    log: EventLog, feed: Any, handlers: Mapping[str, Callable[[Entry], None]], stop: threading.Event
) -> list[threading.Thread]:
    """Hand each stream of `handlers` (name to handler) every entry the log retains, then each new one, one thread
    per stream until `stop`. Each waits for the Board replay: an event lands on the pull requests its task cites,
    which the feed knows only once it has read the Board. An entry applied twice leaves the store as once did, so a
    restart replays them all."""
    from starpulse._internal.eventlog.event_log import Tail  # noqa: PLC0415 - the database stack loads when a log opens

    def run(stream: str, handle: Callable[[Entry], None]) -> None:
        feed.wait_replayed()
        Tail(log, stream, after=0, interval=POLL_S).run(handle, stop)

    threads = [
        threading.Thread(target=run, args=item, name=f"pull-events-{item[0]}", daemon=True) for item in handlers.items()
    ]
    for thread in threads:
        thread.start()
    return threads


class NotingFeed:
    """The worker's feed: `note_actor` is also sent to the serving feed, which sees the lane move the actor's write makes."""

    def __init__(self, feed: Any, log: EventLog) -> None:
        self._feed = feed
        self._log = log

    def __getattr__(self, name: str) -> Any:
        return getattr(self._feed, name)

    def note_actor(self, task_id: str, actor: str | None, session: str = "", harness: str = "") -> None:
        self._log.append(NOTES_STREAM, {"task": task_id, "actor": actor, "session": session, "harness": harness})
        self._feed.note_actor(task_id, actor, session, harness)


class Notes:
    """The actor notes the worker makes from now on, each applied to `feed` once: by `run`'s thread as they land, and
    by `catch_up` on the thread placing a move, since the worker logs its note before the write the move comes from."""

    def __init__(self, log: EventLog, feed: Any) -> None:
        from starpulse._internal.eventlog.event_log import Tail  # noqa: PLC0415 - the database stack loads when a log opens

        self._log = log
        self._feed = feed
        self._tail = Tail(log, NOTES_STREAM, after=log.head() or 0, interval=POLL_S)
        self._lock = threading.Lock()

    def catch_up(self) -> None:
        """Apply every note logged since the last read; raises when the database is unreachable."""
        with self._lock:
            while True:
                entries = self._tail.poll()
                for entry in entries:
                    fields = entry.fields
                    self._feed.note_actor(
                        fields["task"], fields["actor"], fields.get("session", ""), fields.get("harness", "")
                    )
                if len(entries) < self._tail.batch:
                    return

    def run(self, stop: threading.Event) -> None:
        """Catch up on each append until `stop`; a read that fails is retried after `POLL_S`."""
        while not stop.is_set():
            seen = self._log.appends  # before the read, so an append during it still ends the wait below
            try:
                self.catch_up()
            except Exception as exc:  # the database is unreachable or locked; the next read retries
                logger.warning("pull-notes: read failed, retrying in %ss: %s", POLL_S, exc)
                stop.wait(POLL_S)
                continue
            self._log.wait_for_append(seen, POLL_S, stop)


def follow_notes(log: EventLog, feed: Any, stop: threading.Event) -> threading.Thread:
    """Apply each actor note the worker makes from now on to `feed`, on a thread until `stop`, and let a feed that
    reads them (`BoardFeed.read_notes`) catch up before it places a move no note names yet."""
    notes = Notes(log, feed)
    if hasattr(feed, "read_notes"):
        feed.read_notes(notes.catch_up)
    thread = threading.Thread(target=notes.run, args=(stop,), name="pull-notes", daemon=True)
    thread.start()
    return thread


def publish_metrics(log: EventLog, text: str) -> None:
    """Keep the worker's exposition `text` for `serve` to relay."""
    try:
        log.set_setting(METRICS, text)
    except Exception:
        logger.warning("pulls: the metrics were not kept", exc_info=True)


def keep_metrics(log: EventLog, exposition: Callable[[], str], stop: threading.Event) -> threading.Thread:
    """Write `exposition()` to the log every `METRICS_S` on a thread until `stop`."""

    def run() -> None:
        while not stop.is_set():
            publish_metrics(log, exposition())
            stop.wait(METRICS_S)

    thread = threading.Thread(target=run, name="pull-metrics", daemon=True)
    thread.start()
    return thread


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The worker's metrics text as last kept; empty before it kept any or when the log cannot be read."""

    def read() -> str:
        try:
            text = log.setting(METRICS)
        except Exception:
            return ""
        return text if isinstance(text, str) else ""

    return read
