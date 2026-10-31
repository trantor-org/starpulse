"""The Delivery context's seam with `serve`: the projection out, the refresh requests and metrics across.

The Delivery worker (`starpulse worker pulls`) is the one writer of the pull store and the one reader of GitHub; `serve`
keeps the store read-only. What the worker projects, and what `serve` must say back to it, cross the event log:

- the worker keeps its latest projection in the `PROJECTION` worker state; `serve` applies it to its feed (`Projected`)
  when the state's version moves, so snapshots keep drawing pull request state;
- the worker announces the records of each save on `SAVED_STREAM` (`announce_saves`); `serve` holds records in memory
  and takes those from the database again (`follow_saves`), so `/api/pulls` never answers from before a save;
- a page's refresh request lands on `REFRESH_STREAM` (`request_refresh`) and the worker asks `PullSync` for it;
- the actor's `/metrics` text is kept in the `METRICS` worker state for `serve` to relay;
- the poller writes the time to the `POLLER` worker state while it runs (`keep_beating`), and `starpulse doctor` reports it
  down once that is older than `DOWN_S` (`poller_problem`).
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import Entry, EventLog
    from starpulse.pulls.adapters.outbound.pulls import PullStore

logger = logging.getLogger(__name__)

PROJECTION = "pulls.projection"
METRICS = "pulls.metrics"
SAVED_STREAM = "pulls:saved"
REFRESH_STREAM = "pulls:refresh"
POLLER = "pulls.poller"
#: Seconds between the worker's writes of its metrics.
METRICS_S = 15.0
#: Seconds between the poller's beats, and how old its last beat may be before `serve` calls it down.
BEAT_S = 15.0
DOWN_S = 60.0
#: Seconds an idle tail waits for an append from another process.
POLL_S = 1.0


def _follow(name: str, log: EventLog, stream: str, after: int, handle: Callable[[Entry], None], stop: threading.Event):

    tail = log.tail(stream, after=after, interval=POLL_S)
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

    def apply(self) -> None:
        """Take the kept projection; none kept yet, or one unreadable, leaves the feed as it was.

        A projection kept before a pull carried its `repo` (TASK-7845) is unreadable: its pulls fail the snapshot
        contract, so every `/api/snapshot` would 500 until the worker keeps a new one.
        """
        try:
            _, body = self._log.state(PROJECTION)
        except Exception:
            logger.warning("pulls: the projection was not read", exc_info=True)
            return
        if isinstance(body, dict) and isinstance(body.get("pulls"), dict) and isinstance(body.get("answers"), dict):
            records = [pull for pulls in body["pulls"].values() for pull in pulls]
            if all(isinstance(pull, dict) and "repo" in pull for pull in records):
                self._feed.set_pulls(body["pulls"], body["answers"])

    def follow(self, stop: threading.Event) -> threading.Thread:
        """Apply the kept projection now, then each one announced after, on a thread until `stop`."""
        thread = self._log.follow_state(PROJECTION, self.apply, stop, interval=POLL_S, thread_name="pull-projected")
        self.apply()
        return thread


def announce_saves(store: PullStore, log: EventLog) -> None:
    """Announce the keys of each save `store` makes on `SAVED_STREAM`, for the serving store to refresh."""
    store.subscribe_saves(lambda keys: log.publish(SAVED_STREAM, {"keys": json.dumps(keys)}))


def follow_saves(store: PullStore, log: EventLog, stop: threading.Event, after: int) -> threading.Thread:
    """Refresh `store` with the records of each save announced past `after`, on a thread until `stop`. `after` is read
    before the store loads, so a save between the load and the follow is not missed."""

    def handle(entry: Entry) -> None:
        store.refresh([(repo, int(number)) for repo, number in json.loads(entry.fields["keys"])])

    store.keep_listings()
    return _follow("pull-saved", log, SAVED_STREAM, after, handle, stop)


def request_refresh(log: EventLog, tracked: Callable[[], list[str]]) -> Callable[[str, int], bool]:
    """A refresh request for `serve`'s page: queued for the worker when `repo` is tracked, refused (False) otherwise."""

    def request(repo: str, number: int) -> bool:
        if repo not in tracked():
            return False
        log.publish(REFRESH_STREAM, {"repo": repo, "number": number})
        return True

    return request


def follow_refreshes(log: EventLog, request: Callable[[str, int], Any], stop: threading.Event) -> threading.Thread:
    """Hand each refresh asked from now on to `request` (the pull sync's), on a thread until `stop`. A request asked
    since the last poller's beat went unserved while no worker ran, so those replay: a restart must not drop the
    close of a pull request that landed in the gap."""
    _, beat = log.state(POLLER)
    since = beat.get("at") if isinstance(beat, dict) else None
    head = log.head() or 0

    def handle(entry: Entry) -> None:
        if entry.id > head or entry.at >= (since or math.inf):
            request(entry.fields["repo"], int(entry.fields["number"]))

    return _follow("pull-refresh", log, REFRESH_STREAM, head if since is None else 0, handle, stop)


def follow_events(
    log: EventLog, feed: Any, handlers: Mapping[str, Callable[[Entry], None]], stop: threading.Event
) -> list[threading.Thread]:
    """Hand each stream of `handlers` (name to handler) every entry the log retains, then each new one, until `stop`.
    Each waits for the Board replay: an event lands on the pull requests its task cites, which the feed knows only
    once it has read the Board. An entry applied twice leaves the store as once did, so a restart replays them all.

    The replay of a stream's retention takes minutes (the `machine:events` stream holds a month), and a `PR_MERGED`
    published meanwhile would wait behind it. So each stream has a second thread on a `Tail.live` taken before the
    replay starts, which reads only what is appended from then on. A lock per stream lets one entry run at a time."""
    from starpulse.event_log.event_log import Tail  # noqa: PLC0415 -- the event log opens the database stack

    def run(stream: str, handle: Callable[[Entry], None], lock: threading.Lock, tail: Tail) -> None:
        feed.wait_replayed()

        def locked(entry: Entry) -> None:
            with lock:
                handle(entry)

        tail.run(locked, stop)

    threads = []
    for stream, handle in handlers.items():
        lock = threading.Lock()
        live = Tail.live(log, stream, interval=POLL_S)
        replay = log.tail(stream, after=0, interval=POLL_S)
        for kind, tail in (("replay", replay), ("live", live)):
            name = f"pull-events-{stream}-{kind}"
            threads.append(threading.Thread(target=run, args=(stream, handle, lock, tail), name=name, daemon=True))
    for thread in threads:
        thread.start()
    return threads


def publish_metrics(log: EventLog, text: str) -> None:
    """Keep the worker's exposition `text` for `serve` to relay."""
    try:
        log.put_state(METRICS, text)
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


def keep_beating(
    log: EventLog, running: threading.Event, stop: threading.Event, clock: Callable[[], float] = time.time
) -> threading.Thread:
    """Write the time to the log every `BEAT_S` while `running` is set, on a thread until `stop`: the poller's beat."""

    def run() -> None:
        while not stop.is_set():
            if running.is_set():
                try:
                    log.put_state(POLLER, {"at": clock()})
                except Exception:
                    logger.warning("pulls: the poller's beat was not kept", exc_info=True)
            stop.wait(BEAT_S)

    thread = threading.Thread(target=run, name="pull-beat", daemon=True)
    thread.start()
    return thread


def poller_problem(log: EventLog, clock: Callable[[], float] = time.time) -> Callable[[], str | None]:
    """Why the pull poller counts as down, or None while its beat is under `DOWN_S` old."""

    def read() -> str | None:
        try:
            _, beat = log.state(POLLER)
        except Exception as exc:
            return f"the event log cannot be read: {exc}"
        at = beat.get("at") if isinstance(beat, dict) else None
        if not isinstance(at, int | float):
            return "the pull poller has not reported"
        age = clock() - at
        return None if age <= DOWN_S else f"the pull poller last reported {age:.0f}s ago"

    return read


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The worker's metrics text as last kept; empty before it kept any or when the log cannot be read."""

    def read() -> str:
        try:
            _, text = log.state(METRICS)
        except Exception:
            return ""
        return text if isinstance(text, str) else ""

    return read
