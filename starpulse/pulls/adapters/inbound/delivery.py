"""The Delivery context's seam with `serve`: the projection out and metrics across.

The Delivery worker (`starpulse worker pulls`) is the one writer of the pull store; `serve`
keeps the store read-only. What the worker projects, and what `serve` must say back to it, cross the event log:

- the worker keeps its latest projection in the `PROJECTION` worker state; `serve` applies it to its feed (`Projected`)
  when the state's version moves, so snapshots keep drawing pull request state;
- the worker announces the records of each save on `SAVED_STREAM` (`announce_saves`); `serve` holds records in memory
  and takes those from the database again (`refresh_on_save`, at a request), so `/api/pulls` never answers from before a save
  (the worker also stores the unfiltered answer with its gzip, which `serve` sends as it is);
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
SAVED_STREAM = "pulls:saved"
#: The worker state holding, by stream, the id of the last entry a replay handed over: the `follow_events` streams.
CURSOR = "pulls.cursor"


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

        A projection kept before a pull carried its `repo` is unreadable: its pulls fail the snapshot
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


def refresh_on_save(store: PullStore) -> Callable[[Entry], None]:
    """The handler of each save announced on `SAVED_STREAM`: it refreshes `store` with the records the save made. The
    cursor it is read from is taken before the store loads, so a save between the load and the read is not missed."""
    store.keep_listings()

    def handle(entry: Entry) -> None:
        store.refresh([(repo, int(number)) for repo, number in json.loads(entry.fields["keys"])])

    return handle


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
) -> threading.Thread:
    """Write `exposition()` to the log after each turn the actor sets `turned` for, when it differs from what was last
    written, on a thread until `stop`."""

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
        finally:
            stop.unlisten(turned.set)

    thread = threading.Thread(target=run, name="pull-metrics", daemon=True)
    thread.start()
    return thread


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The worker's metrics text as last kept; empty before it kept any or when the log cannot be read."""
    return kept_text(log, METRICS)
