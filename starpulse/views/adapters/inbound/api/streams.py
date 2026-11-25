"""The event streams as Starlette endpoints over frame generators. The snapshot module and `/graphql` route them."""

import contextlib
import functools
import json
import logging
import queue
import threading
import time
from collections.abc import Awaitable, Callable, Generator, Iterator, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from starpulse.contracts.api.registry import EVENTS
from starpulse.views.adapters.inbound.api.answering import PLACE, answer, query, reading
from starpulse.views.adapters.inbound.api.table import Stream
from starpulse.views.adapters.inbound.column_stream import ColumnViews, Interest
from starpulse.views.application.queries.responses import _error
from starpulse.views.model.encoding import encode, event

if TYPE_CHECKING:  # annotation only: `snapshots` and the feed are built by the caller
    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.views.adapters.inbound.snapshots import Snapshots

logger = logging.getLogger(__name__)


#: Seconds a stream refused for a full stream pool is asked to wait before it reconnects.
_STREAM_RETRY_S = 5
#: Reads of the snapshot a stream tries to attach to before it refuses (a 503) instead of spinning a thread.
_ATTACH_READS = 8


class Unattachable(Exception):
    """No stored snapshot's deltas could be attached to: the caller answers 503 and the page retries."""


def _attach(attempt: Callable[[], Any]) -> Any:
    """`attempt`'s result once it attaches (not None), within `_ATTACH_READS` tries; `Unattachable` after that."""
    for _ in range(_ATTACH_READS):
        if (attached := attempt()) is not None:
            return attached
    raise Unattachable


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


#: The headers of a stream's response, which a HEAD request is answered with alone.
EVENT_HEADERS = {"content-type": "text/event-stream", "cache-control": "no-store"}


class Events(StreamingResponse):
    """An open stream's response: the frames the page reads, until it leaves or the server ends the stream."""

    def __init__(self, request: Request, stream: Stream) -> None:
        super().__init__(request.app.state.pump(stream.frames), headers=EVENT_HEADERS)
        self._stream = stream

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with contextlib.suppress(ValueError):  # a frame still being made on an abandoned thread: its generator is
                self._stream.frames.close()  # closed once that frame is dropped
            self._stream.release()


def streaming(work: Callable[[Request], Response]) -> Callable[[Request], Awaitable[Response]]:
    """`work`, which blocks while it opens a stream, as a Starlette endpoint that runs it on a worker thread."""
    opening = reading(work)

    @functools.wraps(work)
    async def endpoint(request: Request) -> Response:
        if request.method == "HEAD":
            return Response(headers=EVENT_HEADERS)  # the headers a GET sends, without opening a stream
        return await opening(request)

    return endpoint


def _frame(name: str, data: str) -> bytes:
    return f"event: {name}\ndata: {data}\n\n".encode()


class Streams:
    """The streams the page holds open: the Board's events, a session's held tasks, the lanes and one Ledger's rows. Each
    handler answers a `Request` with the `Events` to write, or a `Response` where it refuses to open one; it takes its
    place among the streams open from the request's `Place`."""

    def __init__(
        self,
        feed: BoardFeed,
        snapshots: Snapshots,
        build: Callable[[], str | None] = lambda: None,
        ready: Callable[[], dict[str, Any]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._feed = feed
        self._snapshots = snapshots
        self._build = build
        self._ready = ready
        self._clock = clock
        self._event_text = EventText()
        self._unmodelled: set[str] = {"tick"}  # the held snapshot's clock tick is stored for it, and is no page event
        self._column_views = ColumnViews()

    def board(self, request: Request) -> Response:
        by_ref = query(request).get("snapshot") == ["ref"]
        return self._admitted(request, lambda: self._events(by_ref))

    def held(self, request: Request) -> Response:
        assignee = (query(request).get("assignee") or [""])[0]
        if not assignee:
            return answer(request, _error("name the session: /api/held?assignee=<session>"), 400)
        return self._admitted(request, lambda: self._columns("held", assignee))

    def lanes(self, request: Request) -> Response:
        states = query(request).get("state", [])
        return self._admitted(request, lambda: self._columns("lanes", None, states))

    def task_changes(self, request: Request, position: int, render: Callable[[dict], str]) -> Response:
        """The task changes after stream `position`, each as a `next` event of `render`'s text; a 410 whose error code is
        `REREAD` when the store no longer holds the deltas after `position`."""
        return self._changes(
            request, position, "the task list", lambda name, data: self._task_change(render, name, data)
        )

    def job_changes(self, request: Request, position: int, render: Callable[[dict], str]) -> Response:
        """`task_changes` for the jobs: a `next` event of `render`'s text for each change of the workflows."""
        return self._changes(request, position, "the jobs", lambda name, data: self._job_change(render, name, data))

    def health(self, request: Request, render: Callable[[dict], str]) -> Response:
        """The server's health as a `next` event of `render`'s text when it connects, then another each time the components,
        the build or the restart change. The stream attaches at the log's head, so an announcement made after the connect
        reaches it before the worker exits."""

        def open_stream() -> Stream:
            _, changes = _attach(lambda: self._snapshots.watch_from(self._snapshots.position()))
            return Stream(self._health_frames(render, changes), lambda: self._snapshots.unsubscribe(changes))

        return self._admitted(request, open_stream)

    def _health_frames(self, render: Callable[[dict], str], changes: queue.Queue) -> Generator[bytes]:
        """The components are read on connect, at least every `_PING_S` however busy the stream is, and on each delta while
        one is not ready or once the server announced it restarts: a ready server's deltas cost it no read in between."""
        sent, restarting, unready, unmarked = None, False, False, False
        while True:
            state = self._health(restarting)
            unready = not all(component["ready"] for component in state["components"])
            if state != sent:
                sent = state
                yield _frame("next", render({**state, "at": self._clock()}))
            if unmarked:
                changes.task_done()  # `Snapshots.announce` waits for the mark of what it queued: after the frame is sent
                unmarked = False
            due = time.monotonic() + _PING_S
            while True:
                try:
                    change = changes.get(timeout=max(0.0, due - time.monotonic()))
                except queue.Empty:
                    yield _PING
                    break
                if change is None:  # the log was renumbered: the page reconnects
                    changes.task_done()
                    return
                unmarked = True
                restarting = restarting or change[0] == "restarting"
                if unready or restarting or time.monotonic() >= due:
                    break
                changes.task_done()
                unmarked = False

    def _health(self, restarting: bool) -> dict[str, Any]:
        report = self._ready() if self._ready else {"components": {}}
        build = self._build()
        return {
            "components": [{"name": name, **component} for name, component in report["components"].items()],
            "build": json.loads(build)["id"] if build else None,
            "restarting": restarting,
        }

    def scheduler_changes(self, request: Request, position: int, render: Callable[[dict], str]) -> Response:
        """`task_changes` for the scheduler: a `next` event of `render`'s text for each status it publishes."""
        return self._changes(
            request, position, "the scheduler", lambda name, data: self._scheduler_change(render, name, data)
        )

    def _changes(
        self, request: Request, position: int, what: str, frames: Callable[[str, dict], Iterator[bytes]]
    ) -> Response:
        def open_stream() -> Stream | Response:
            if (attached := self._snapshots.watch_from(position)) is None:
                message = f"stream position {position} is no longer held: read {what} again"
                gone = {"errors": [{"message": message, "extensions": {"code": "REREAD"}}]}
                return answer(request, encode("graphql", gone), 410)
            missed, changes = attached
            return Stream(self._deltas(missed, changes, frames), lambda: self._snapshots.unsubscribe(changes))

        return self._admitted(request, open_stream)

    def ledger_changes(self, request: Request, event: str, render: Callable[[dict], str]) -> Response:
        """`event`'s newest rows as the first `next` event (`head`), then one for each change to those rows, each of
        `render`'s text; a 404 when no workflow is tied to `event`. A page reads this while it has the Ledger open."""

        def open_stream() -> Stream | Response:
            if (watched := self._feed.watch_ledger(event)) is None:
                return answer(request, encode("graphql", {"errors": [{"message": f"no ledger for {event}"}]}), 404)
            page, changes = watched
            return Stream(self._ledger_frames(render, page, changes), lambda: self._feed.unwatch_ledger(changes))

        return self._admitted(request, open_stream)

    def _admitted(self, request: Request, open_stream: Callable[[], Stream | Response]) -> Response:
        if not request.scope[PLACE].take():
            return answer(request, _error("too many open streams; retry shortly"), 503, retry_after=_STREAM_RETRY_S)
        try:
            stream = open_stream()
        except Unattachable:
            request.scope[PLACE].give()
            return answer(request, _error("the Board is still settling; retry shortly"), 503, retry_after=_STREAM_RETRY_S)
        return Events(request, stream) if isinstance(stream, Stream) else stream

    def _events(self, by_ref: bool) -> Stream:
        """The Board's snapshot, then each change as it happens. `by_ref` sends the snapshot as `ref <path>`, the path its
        body is read from: a browser reads a long event on its main thread, a fetched body off it."""
        encoded = None

        def attempt() -> tuple | None:  # else the deltas past that body were pruned: read the newer one stored
            nonlocal encoded
            seq, encoded = self._snapshots.stored()
            return self._snapshots.watch_from(seq)

        missed, changes = _attach(attempt)
        key = self._snapshots.hold(encoded) if by_ref else None
        first = f"ref /api/events/body/{key}" if key is not None else encoded.body.decode()

        def release() -> None:
            self._snapshots.unsubscribe(changes)
            if key is not None:
                self._snapshots.release(key)

        return Stream(self._event_frames(first, missed, changes), release)

    def _event_frames(self, first: str, missed: Sequence, changes: queue.Queue) -> Generator[bytes]:
        yield _frame("snapshot", first)
        if (build := self._build()) is not None:
            yield _frame("build", build)  # a page holding another build than this one is out of date
        yield from self._deltas(missed, changes, self._event)

    def _deltas(
        self, missed: Sequence, changes: queue.Queue, frames: Callable[[str, dict], Iterator[bytes]]
    ) -> Generator[bytes]:
        """The frames of each delta in `missed`, then of each that arrives on `changes`, pinging while none does; ends
        when the log was renumbered."""
        for change in missed:
            yield from frames(*change)
        while True:
            try:
                change = changes.get(timeout=_PING_S)
            except queue.Empty:
                yield _PING
                continue
            if change is None:  # the log was renumbered: the page reconnects for the body of the new numbering
                changes.task_done()
                return
            try:
                yield from frames(*change)
            finally:
                changes.task_done()  # `Snapshots.announce` waits for the marks of what it queued

    def _task_change(self, render: Callable[[dict], str], name: str, data: dict) -> Iterator[bytes]:
        if name == "task":
            settled = data.get("settled")
            change = {"id": data["id"], "machine": "board", "task": self._feed.task(data["id"])}
            yield _frame("next", render({**change, "settled": settled and {"id": data["id"], **settled}}))
        elif name == "move":
            yield _frame("next", render({"id": data["id"], "machine": data["machine"], "machineTask": data["agent"]}))

    def _job_change(self, render: Callable[[dict], str], name: str, data: dict) -> Iterator[bytes]:
        if name == "dags":
            declared = self._feed.declared_jobs()
            yield _frame(
                "next",
                render(
                    {
                        "jobs": data["dags"],
                        "error": data["error"],
                        "pools": data["pools"],
                        "domains": declared["domains"],
                        "cues": declared["cues"],
                    }
                ),
            )

    def _scheduler_change(self, render: Callable[[dict], str], name: str, data: dict) -> Iterator[bytes]:
        if name == "scheduler":
            by_harness = [{"harness": harness, **sessions} for harness, sessions in data.get("sessionsByHarness", {}).items()]
            yield _frame("next", render({**data, "sessionsByHarness": by_harness or None}))

    def _event(self, name: str, data: dict) -> Iterator[bytes]:
        if name in EVENTS:
            try:
                text = self._event_text(name, data)
            except ValidationError:  # the page reads the stored snapshot in place of the delta it cannot be sent
                logger.exception("StarPulse: /api/events cannot encode a `%s` delta; the page is sent the stored snapshot", name)
                yield _frame("snapshot", self._snapshots.stored()[1].body.decode())
            else:
                yield _frame(name, text)
        elif name not in self._unmodelled:
            self._unmodelled.add(name)
            logger.error("StarPulse: /api/events has no event `%s`; its deltas are skipped", name)

    def _ledger_frames(
        self, render: Callable[[dict], str], page: dict, changes: queue.Queue
    ) -> Generator[bytes]:
        yield _frame("next", render({"head": True, **page}))
        while True:
            try:
                yield _frame("next", render({"head": False, "more": False, **changes.get(timeout=_PING_S)}))
            except queue.Empty:
                yield _PING

    def _columns(self, event: str, assignee: str | None, states: Sequence[str] = ()) -> Stream:
        """The Board's columns (only `states`, when named) with the tasks `assignee` holds (all, when None), as `event`,
        then again each time a change alters that view. A burst of changes settles before one reread, and the streams
        that reread for a change read one build of the columns."""
        served = self._column_views.take(self._snapshots)

        def attempt() -> tuple | None:
            nonlocal served
            if (attached := self._snapshots.watch_from(served.seq)) is None:
                served = self._column_views.take(self._snapshots)
            return attached

        missed, changes = _attach(attempt)
        if missed:  # the view must include what was published after the snapshot it started from
            served = self._column_views.take(self._snapshots)
        return Stream(
            self._column_frames(event, assignee, states, served, changes), lambda: self._snapshots.unsubscribe(changes)
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
            if (yield from self._wait_touched(changes, interest)):
                return
            # adr-exempt: debounce
            time.sleep(_HELD_SETTLE_S)
            while not changes.empty():
                renumbered = changes.get_nowait() is None
                changes.task_done()
                if renumbered:
                    return
            served = self._column_views.take(self._snapshots)

    def _wait_touched(self, changes: queue.Queue, interest: Interest) -> Generator[bytes, None, bool]:
        """Take changes off `changes` until one alters the view `interest` describes, pinging while none arrives; True
        when the log was renumbered (a `None`), which ends the stream."""
        while True:
            try:
                change = changes.get(timeout=_PING_S)
            except queue.Empty:
                yield _PING
                continue
            changes.task_done()  # `Snapshots.announce` waits for the marks of what it queued
            if change is None or interest.touched_by(*change):
                return change is None
