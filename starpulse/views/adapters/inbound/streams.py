"""The event streams as frame generators: no socket and no web framework, so the ASGI app (and any
other front) writes the same frames."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Generator, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import parse_qs, unquote

from pydantic import ValidationError

from starpulse.views.adapters.inbound.column_stream import ColumnViews, Interest
from starpulse.views.adapters.inbound.reads import Request, Response
from starpulse.views.adapters.inbound.routes import _HELD, _LANES, _LEDGER, _SNAPSHOT_BODY
from starpulse.views.application.queries.responses import _error
from starpulse.views.model.encoding import encode, event

if TYPE_CHECKING:  # annotation only: `snapshot_cache` and the feed are built by the caller
    from starpulse.board.board_feed import BoardFeed
    from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache

logger = logging.getLogger(__name__)


#: Seconds a stream refused for a full stream pool is asked to wait before it reconnects.
_STREAM_RETRY_S = 5


#: A comment frame, sent while a stream is idle: a closed page fails the write of it, which ends the stream.
_PING = b": ping\n\n"


#: Seconds an idle event stream waits before a keep-alive comment, which is how a closed page is noticed.
_PING_S = 15.0


#: Seconds a held-task stream lets a burst of changes settle before it rereads the holder's tasks.
_HELD_SETTLE_S = 0.5


class EventText:
    """The JSON text of the events last sent, by the data each was made from.

    Every page streaming `/api/events` is handed the same `data` object for a change, and encoding it holds the GIL
    (the `ledgers` event is ~0.7 MB, ~45 ms), so the first page to reach a change encodes it under the lock and the
    others take that text.
    """

    def __init__(self, keep: int = 8) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._made: dict[int, tuple[str, Any, str]] = {}

    def __call__(self, name: str, data: Any) -> str:
        with self._lock:
            made = self._made.get(id(data))
            if made is not None and made[0] == name and made[1] is data:
                return made[2]
            text = event(name, data)
            self._made[id(data)] = (name, data, text)  # holds `data`, so its id is not reused while it is here
            while len(self._made) > self._keep:
                del self._made[next(iter(self._made))]
            return text


Admit = Callable[[], bool]
StreamHandler = Callable[[Request, Admit], "Stream | Response"]


class Stream(NamedTuple):
    """An open stream: `frames` are the bytes to write, in order, until the client leaves (the caller then closes the
    generator); `release` detaches the stream from the feed once it ends."""

    frames: Generator[bytes]
    release: Callable[[], None]


def _frame(name: str, data: str) -> bytes:
    return f"event: {name}\ndata: {data}\n\n".encode()


class Streams:
    """The streams the page holds open: the Board's events, a session's held tasks, the lanes and one Ledger's rows. A
    route answers a `Request` with the `Stream` to write, or a `Response` where it refuses to open one."""

    def __init__(
        self,
        feed: BoardFeed,
        snapshots: SnapshotCache,
        build: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._feed = feed
        self._snapshots = snapshots
        self._build = build
        self._event_text = EventText()
        self._column_views = ColumnViews()

    def routes(self) -> list[tuple[str, StreamHandler]]:
        """Every stream as its path template (`ReadRoutes.routes` says how it is written) and its handler, which takes
        the request and `admit`, which moves the connection's worker into the stream pool and says whether there was
        room."""
        return [
            ("/api/events", self._board),
            (_HELD, self._held),
            (_LANES, self._lanes),
            (f"{_LEDGER}{{rest:path}}/events", self._ledger_rows),
        ]

    def _board(self, request: Request, admit: Admit) -> Stream | Response:
        by_ref = parse_qs(request.query).get("snapshot") == ["ref"]
        return self._admitted(admit, lambda: self._events(by_ref))

    def _held(self, request: Request, admit: Admit) -> Stream | Response:
        assignee = (parse_qs(request.query).get("assignee") or [""])[0]
        if not assignee:
            return Response(_error(f"name the session: {_HELD}?assignee=<session>"), 400)
        return self._admitted(admit, lambda: self._columns("held", assignee))

    def _lanes(self, request: Request, admit: Admit) -> Stream | Response:
        states = parse_qs(request.query).get("state", [])
        return self._admitted(admit, lambda: self._columns("lanes", None, states))

    def _ledger_rows(self, request: Request, admit: Admit) -> Stream | Response:
        event = unquote(request.path.removeprefix(_LEDGER).partition("/")[0])
        return self._admitted(admit, lambda: self._ledger(event))

    def _admitted(self, admit: Admit, open_stream: Callable[[], Stream | Response]) -> Stream | Response:
        if not admit():
            return Response(_error("too many open streams; retry shortly"), 503, retry_after=_STREAM_RETRY_S)
        return open_stream()

    def _events(self, by_ref: bool) -> Stream:
        """The Board's snapshot, then each change as it happens. `by_ref` sends the snapshot as `ref <path>`, the path its
        body is read from: a browser reads a long event on its main thread, a fetched body off it."""
        # The held snapshot is sent as it is, however many changes it lacks, so a page connecting while the next
        # one is built is not held up by it: it applies those changes after it.
        served = self._snapshots.latest() or self._snapshots.get()
        while (attached := self._feed.watch_from(served.sent)) is None:
            served = self._snapshots.get()
        missed, changes = attached
        return Stream(self._event_frames(served, by_ref, missed, changes), lambda: self._feed.unsubscribe(changes))

    def _event_frames(self, served, by_ref: bool, missed: Sequence, changes: queue.Queue) -> Generator[bytes]:
        try:
            yield _frame("snapshot", f"ref {_SNAPSHOT_BODY}{served.key}" if by_ref else served.body.decode())
            if (build := self._build()) is not None:
                yield _frame("build", build)  # a page holding another build than this one is out of date
            for change in missed:
                yield self._event(*change)
            while True:
                try:
                    change = changes.get(timeout=_PING_S)
                except queue.Empty:
                    yield _PING
                    continue
                try:
                    yield self._event(*change)
                finally:
                    changes.task_done()  # `feed.announce` waits for the marks of what it queued
        except ValidationError:
            logger.exception("StarPulse: /api/events sent a body its model refuses; the stream ends")

    def _event(self, name: str, data: dict) -> bytes:
        return _frame(name, self._event_text(name, data))

    def _ledger(self, event: str) -> Stream | Response:
        """`event`'s newest rows as a `page` event (`{rows, more}`), then a `rows` event (`{rows}`) each time rows of that
        Ledger change. A page reads this while it has the Ledger open; the main stream carries no row."""
        if (watched := self._feed.watch_ledger(event)) is None:
            return Response(_error(f"no ledger for {event}"), 404)
        rows, more, changes = watched
        return Stream(self._ledger_frames(rows, more, changes), lambda: self._feed.unwatch_ledger(changes))

    def _ledger_frames(self, rows: list, more: bool, changes: queue.Queue) -> Generator[bytes]:
        yield _frame("page", encode("ledger", {"rows": rows, "more": more}).decode())
        while True:
            try:
                yield _frame("rows", encode("ledger_rows", changes.get(timeout=_PING_S)).decode())
            except queue.Empty:
                yield _PING

    def _columns(self, event: str, assignee: str | None, states: Sequence[str] = ()) -> Stream:
        """The Board's columns (only `states`, when named) with the tasks `assignee` holds (all, when None), as `event`,
        then again each time a change alters that view. A burst of changes settles before one reread, and the streams
        that reread for a change read one build of the columns."""
        served = self._snapshots.after_current()
        while (attached := self._feed.watch_from(served.sent)) is None:
            served = self._snapshots.after_current()
        missed, changes = attached
        if missed:
            served = (
                self._snapshots.after_current()
            )  # the view must include what was published after the snapshot it started from
        return Stream(
            self._column_frames(event, assignee, states, served, changes), lambda: self._feed.unsubscribe(changes)
        )

    def _column_frames(
        self, event: str, assignee: str | None, states: Sequence[str], served, changes: queue.Queue
    ) -> Generator[bytes]:
        sent = None
        while True:
            view, text = self._column_views.render(served, assignee, states)
            if view != sent:
                yield _frame(event, text)
                sent = view
                interest = Interest(view, assignee, states)
            yield from self._wait_touched(changes, interest)
            time.sleep(_HELD_SETTLE_S)
            while not changes.empty():
                changes.get_nowait()
                changes.task_done()
            served = self._snapshots.after_current()

    def _wait_touched(self, changes: queue.Queue, interest: Interest) -> Generator[bytes]:
        """Take changes off `changes` until one alters the view `interest` describes, pinging while none arrives."""
        while True:
            try:
                change = changes.get(timeout=_PING_S)
            except queue.Empty:
                yield _PING
                continue
            changes.task_done()  # `feed.announce` waits for the marks of what it queued
            if interest.touched_by(*change):
                return
