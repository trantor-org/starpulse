"""The Delivery context's seam with `serve`: the projection out, the refresh requests, actor notes and metrics across.

The Delivery worker (`starpulse worker pulls`) is the one writer of the pull store and the one reader of GitHub; `serve`
keeps the store read-only. What the worker projects, and what `serve` must say back to it, cross the event log:

- the worker keeps its latest projection in the `PROJECTION` setting and announces each change on `PROJECTED_STREAM`;
  `serve` applies it to its feed (`Projected`), so snapshots keep drawing pull request state;
- a page's refresh request lands on `REFRESH_STREAM` (`request_refresh`) and the worker asks `PullSync` for it;
- the task actor's lane attributions land on `NOTES_STREAM` so the serving feed names the actor on the lane move the
  board file's change produces (`NotingFeed`, `follow_notes`); a note that arrives after the move it names is lost, as
  a note the move outlived always was;
- the actor's `/metrics` text is kept in the `METRICS` setting for `serve` to relay.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from starpulse._internal.eventlog.event_log import Entry, EventLog, Tail

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


def follow_notes(log: EventLog, feed: Any, stop: threading.Event) -> threading.Thread:
    """Apply each actor note the worker makes from now on to `feed`, on a thread until `stop`."""

    def handle(entry: Entry) -> None:
        fields = entry.fields
        feed.note_actor(fields["task"], fields["actor"], fields.get("session", ""), fields.get("harness", ""))

    return _follow("pull-notes", log, NOTES_STREAM, log.head() or 0, handle, stop)


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
