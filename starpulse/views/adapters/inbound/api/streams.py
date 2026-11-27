"""The event streams as Starlette endpoints over frame generators. `/graphql` routes them."""

import contextlib
import logging
import queue
import time
from collections.abc import Callable, Generator, Iterator, Sequence
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from starpulse.views.adapters.inbound.api.answering import PLACE, answer
from starpulse.views.adapters.inbound.api.table import Stream
from starpulse.views.application.queries.responses import _error
from starpulse.views.model.encoding import encode

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


def _frame(name: str, data: str) -> bytes:
    return f"event: {name}\ndata: {data}\n\n".encode()


class Streams:
    """The streams the page holds open: the task, job and scheduler changes, the server's health and one Ledger's rows. Each
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
        return {
            "components": [{"name": name, **component} for name, component in report["components"].items()],
            "build": self._build(),
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

    def _deltas(
        self, missed: Sequence, changes: queue.Queue, frames: Callable[[str, dict], Iterator[bytes]]
    ) -> Generator[bytes]:
        """The frames of each delta in `missed`, then of each that arrives on `changes`, pinging once `_PING_S` pass with no
        byte sent, however many changes this stream draws nothing for; ends when the log was renumbered."""
        for change in missed:
            yield from frames(*change)
        due = time.monotonic() + _PING_S
        while True:
            if time.monotonic() >= due:
                yield _PING
                due = time.monotonic() + _PING_S
            try:
                change = changes.get(timeout=max(0.0, due - time.monotonic()))
            except queue.Empty:
                continue
            if change is None:  # the log was renumbered: the page reconnects for the body of the new numbering
                changes.task_done()
                return
            try:
                for frame in frames(*change):
                    yield frame
                    due = time.monotonic() + _PING_S
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

    def _ledger_frames(
        self, render: Callable[[dict], str], page: dict, changes: queue.Queue
    ) -> Generator[bytes]:
        yield _frame("next", render({"head": True, **page}))
        while True:
            try:
                yield _frame("next", render({"head": False, "more": False, **changes.get(timeout=_PING_S)}))
            except queue.Empty:
                yield _PING
