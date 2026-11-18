"""The Delivery context's seam with `serve`: the projection out, the refresh requests and metrics across.

The Delivery worker (`starpulse worker pulls`) is the one writer of the pull store and the one reader of GitHub; `serve`
keeps the store read-only. What the worker projects, and what `serve` must say back to it, cross the event log:

- the worker keeps its latest projection in the `PROJECTION` worker state; `serve` applies it to its feed (`Projected`)
  when the state's version moves, so snapshots keep drawing pull request state;
- the worker announces the records of each save on `SAVED_STREAM` (`announce_saves`); `serve` holds records in memory
  and takes those from the database again (`follow_saves`), so `/api/pulls` never answers from before a save;
- a page's refresh request lands on `REFRESH_STREAM` (`request_refresh`) and the worker asks `PullSync` for it;
- the actor's `/metrics` text is kept in the `METRICS` worker state for `serve` to relay.

Nothing here beats: a stalled worker shows in the sweeper's `readers` kind, an exit in the supervisor.
"""

import json
import logging
import threading
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.event_log.kept_text import kept_text
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import Entry, EventLog
    from starpulse.pulls.adapters.outbound.pulls import PullStore

logger = logging.getLogger(__name__)

PROJECTION = "pulls.projection"
METRICS = "pulls.metrics"
ACTOR_VIEW = "pulls.actor_view"
SAVED_STREAM = "pulls:saved"
REFRESH_STREAM = "pulls:refresh"
#: The worker state holding, by stream, the id of the last entry a replay handed over: the `follow_events` streams, and
#: `REFRESH_STREAM` once the pull sync serves.
CURSOR = "pulls.cursor"


def _follow(name: str, log: EventLog, stream: str, after: int, handle: Callable[[Entry], None], stop: StopEvent):

    tail = log.tail(stream, after=after)
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
        """Write the feed's projection, unless the log already holds this one. A log that cannot be
        written is tried again on the next call."""
        body = {"pulls": self._feed.pulls(), "answers": self._feed.pull_answers()}
        if body == self._last:
            return
        try:
            self._log.put_state(PROJECTION, body)
        except Exception:
            logger.warning("pulls: the projection was not kept", exc_info=True)
            return
        self._last = body


class Projected:
    """Applies the worker's kept projection to the serving feed."""

    def __init__(self, log: EventLog, feed: Any) -> None:
        self._log = log
        self._feed = feed
        self._applying = threading.Lock()

    def apply(self) -> None:
        """Take the kept projection; none kept yet, or one unreadable, leaves the feed as it was. Applies run one at a
        time, so one that read an older projection never sets the feed after one that read a newer.

        A projection kept before a pull carried its `repo` (TASK-7845) is unreadable: its pulls fail the snapshot
        contract, so every `/api/snapshot` would 500 until the worker keeps a new one.
        """
        with self._applying:
            try:
                _, body = self._log.state(PROJECTION)
            except Exception:
                logger.warning("pulls: the projection was not read", exc_info=True)
                return
            if isinstance(body, dict) and isinstance(body.get("pulls"), dict) and isinstance(body.get("answers"), dict):
                records = [pull for pulls in body["pulls"].values() for pull in pulls]
                if all(isinstance(pull, dict) and "repo" in pull for pull in records):
                    self._feed.set_pulls(body["pulls"], body["answers"])

    def follow(self, stop: StopEvent) -> threading.Thread:
        """Apply the kept projection now, then each one announced after, on a thread until `stop`."""
        thread = self._log.follow_state(PROJECTION, self.apply, stop, thread_name="pull-projected")
        self.apply()
        return thread


def announce_saves(store: PullStore, log: EventLog) -> None:
    """Announce the keys of each save `store` makes on `SAVED_STREAM`, for the serving store to refresh."""
    store.subscribe_saves(lambda keys: log.publish(SAVED_STREAM, {"keys": json.dumps(keys)}))


def follow_saves(store: PullStore, log: EventLog, stop: StopEvent, after: int) -> threading.Thread:
    """Refresh `store` with the records of each save announced past `after`, on a thread until `stop`. `after` is read
    before the store loads, so a save between the load and the follow is not missed."""

    def handle(entry: Entry) -> None:
        store.refresh([(repo, int(number)) for repo, number in json.loads(entry.fields["keys"])])

    store.keep_listings()
    return _follow("pull-saved", log, SAVED_STREAM, after, handle, stop)


def request_refresh(log: EventLog, tracked: Callable[[], list[str]]) -> Callable[[str, int | None], bool]:
    """A refresh request for `serve`'s page: queued for the worker when `repo` is tracked, refused (False) otherwise.
    No `number` asks for every open pull request of `repo`."""

    def request(repo: str, number: int | None) -> bool:
        if repo not in tracked():
            return False
        log.publish(REFRESH_STREAM, {"repo": repo, "number": "" if number is None else number})
        return True

    return request


def follow_refreshes(
    log: EventLog, request: Callable[[str, int | None], Any], serving: threading.Event, stop: StopEvent
) -> threading.Thread:
    """Hand each refresh asked from now on to `request` (the pull sync's), on a thread until `stop`. Each one handed over
    while `serving` is set (the sync is past its Board replay) moves the `REFRESH_STREAM` entry of the `CURSOR` state, and
    the next worker replays those after it: a worker replaced before it served leaves the asks it was handed unserved,
    and a restart must not drop the close of a pull request that landed in the gap."""
    _, kept = log.state(CURSOR)
    cursor = kept.get(REFRESH_STREAM) if isinstance(kept, dict) else None

    def handle(entry: Entry) -> None:
        number = entry.fields["number"]
        request(entry.fields["repo"], int(number) if number != "" else None)
        if serving.is_set():
            log.put_state_entry(CURSOR, REFRESH_STREAM, entry.id)

    return _follow("pull-refresh", log, REFRESH_STREAM, (log.head() or 0) if cursor is None else cursor, handle, stop)


def follow_events(
    log: EventLog,
    feed: Any,
    handlers: Mapping[str, Callable[[Entry], None]],
    stop: StopEvent,
    *,
    resume: bool = False,
) -> list[threading.Thread]:
    """Hand each stream of `handlers` (name to handler) every entry the log retains, then each new one, until `stop`.
    Each waits for the Board replay: an event lands on the pull requests its task cites, which the feed knows only
    once it has read the Board. An entry applied twice leaves the store as once did, so replaying one is harmless.

    The replay of a stream's retention takes minutes (the `machine:events` stream holds a month), and a `PR_MERGED`
    published meanwhile would wait behind it. So each stream has a second thread on a `Tail.live` taken before the
    replay starts, which reads only what is appended from then on. A lock per stream lets one entry run at a time.

    The replay keeps its cursor in the `CURSOR` worker state before each poll, once the batch before is handed over.
    With `resume` (the pull store holds records) it starts after that cursor, so a restart reads only what was
    appended since; without it (a new or wiped store) it reads the whole retention again to rebuild the store."""
    from starpulse.event_log.event_log import Tail  # noqa: PLC0415 -- the event log opens the database stack

    class Kept(Tail):
        """A replay that writes its cursor before each poll: every entry up to it has been handed over."""

        kept: int | None = None

        def poll(self) -> list[Entry]:
            if self.cursor != self.kept:
                log.put_state_entry(CURSOR, self.stream, self.cursor)
                self.kept = self.cursor
            return super().poll()

    def run(stream: str, handle: Callable[[Entry], None], lock: threading.Lock, tail: Tail) -> None:
        feed.wait_replayed()

        def locked(entry: Entry) -> None:
            with lock:
                handle(entry)

        tail.run(locked, stop)

    _, kept = log.state(CURSOR) if resume else (0, None)
    cursors = kept if isinstance(kept, dict) else {}
    threads = []
    for stream, handle in handlers.items():
        lock = threading.Lock()
        live = Tail.live(log, stream)
        replay = Kept(log, stream, after=int(cursors.get(stream) or 0))
        for kind, tail in (("replay", replay), ("live", live)):
            name = f"pull-events-{stream}-{kind}"
            threads.append(threading.Thread(target=run, args=(stream, handle, lock, tail), name=name, daemon=True))
    for thread in threads:
        thread.start()
    return threads


def keep_metrics(
    log: EventLog,
    exposition: Callable[[], str],
    stop: StopEvent,
    turned: threading.Event,
    views: Callable[[], dict[str, Any]] | None = None,
) -> threading.Thread:
    """Write `exposition()`, and the task actor's `views()` when given, to the log after each turn the actor sets
    `turned` for, when it differs from what was last written, on a thread until `stop`."""

    def run() -> None:
        written: dict[str, Any] = {}

        def keep(name: str, read: Callable[[], Any]) -> None:
            try:
                if (value := read()) != written.get(name):
                    log.put_state(name, value)
                    written[name] = value
            except Exception:
                logger.warning("pulls: %s was not kept", name, exc_info=True)

        stop.listen(turned.set)  # a stop wakes the wait below, which then sees it
        try:
            while not stop.is_set():
                turned.wait()
                turned.clear()
                keep(METRICS, exposition)
                if views:
                    keep(ACTOR_VIEW, views)
        finally:
            stop.unlisten(turned.set)

    thread = threading.Thread(target=run, name="pull-metrics", daemon=True)
    thread.start()
    return thread


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The worker's metrics text as last kept; empty before it kept any or when the log cannot be read."""
    return kept_text(log, METRICS)


def actor_views_of(log: EventLog) -> Callable[[], dict[str, Any]]:
    """The task actor's views of the Review tasks as last kept; empty before it kept any or when the log cannot be read."""

    def read() -> dict[str, Any]:
        try:
            _, views = log.state(ACTOR_VIEW)
        except Exception:
            return {}
        return views if isinstance(views, dict) else {}

    return read
