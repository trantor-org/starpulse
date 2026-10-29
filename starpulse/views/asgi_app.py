"""The page as an ASGI app: the page and its assets, the event streams and every `/api` route.

Each handler is a Starlette route and runs (blocking) on a worker thread, so the handlers stay plain functions of a
request; a stream hands its frames to the event loop one at a time. A server such as Hypercorn runs the app, over
HTTP/1.1 or HTTP/2.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import logging
import math
import mimetypes
import os
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, MutableMapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anyio import CancelScope, CapacityLimiter, from_thread, to_thread
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.convertors import PathConvertor, register_url_convertor
from starlette.middleware import Middleware
from starlette.requests import ClientDisconnect
from starlette.requests import Request as Incoming
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.responses import Response as Reply
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.model.seam import Board
from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.runs.cloudevents_grpc import PATH as CLOUDEVENTS_GRPC_PATH
from starpulse.runs.cloudevents_grpc import cloudevents_grpc
from starpulse.views.compression import Encoded, Gzip, accepts_gzip
from starpulse.views.encoding import encode, event
from starpulse.views.gate_request import GateRequest
from starpulse.views.reads import Arrival, Handler, ReadRoutes, Request, Response
from starpulse.views.routes import _PAGES
from starpulse.views.services import Services
from starpulse.views.snapshot_cache import SnapshotCache
from starpulse.views.streams import Stream, StreamHandler, Streams
from starpulse.views.write_routes import WriteHandler, WriteRequest, WriteRoutes

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starlette.types import ASGIApp, Receive, Scope, Send

    from starpulse.board.board_feed import BoardFeed
    from starpulse.flow_metrics.adapters.outbound.history import History


logger = logging.getLogger(__name__)


#: Requests answered at once, each on a worker thread; the next waits for one to finish.
REQUEST_THREADS = 128

#: Streams open at once; a stream past the limit is refused with a 503.
STREAM_LIMIT = 256


#: The Vite build names every file under it by its content's digest, so a new build never reuses a name.
_ASSETS = "/assets/"


_KEPT = "public, max-age=31536000, immutable"


#: The page's scripts are `text/javascript` on every host: the host's MIME table may call them `application/javascript`.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


class _Served(PathConvertor):
    """The path of a file of the build: any but one under `/api`, which only a route answers, so a GET of a write
    answers 405 and a route that does not exist 404."""

    regex = r"(?!api/).*"


register_url_convertor("served", _Served())


@functools.lru_cache(maxsize=4)
def _build_id(path: str, mtime_ns: int) -> str:
    """The digest of the built page's `index.html`, which names every chunk it loads by that chunk's digest: it changes
    exactly when the page a browser would load does. `mtime_ns` keys a rebuilt file afresh."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


@functools.lru_cache(maxsize=4)
def _build_text(build: str) -> str:
    """The `build` event's data for one build id, made once: each connect sends it, and the `EventText` cache of the
    Board's large events must not be spent on it."""
    return event("build", {"id": build})


def page_build(static: Path) -> str | None:
    """The id of the page build `static` holds, or None while it holds none."""
    index = static / "index.html"
    try:
        return _build_id(str(index), index.stat().st_mtime_ns)
    except OSError:
        return None


def build_gauge(static: Path) -> str:
    """`starpulse_page_build_info{build}` for the id the `build` event names `static`'s build; none without a build."""
    if (build := page_build(static)) is None:
        return ""
    name = "starpulse_page_build_info"
    return f'# HELP {name} The id of the page build served.\n# TYPE {name} gauge\n{name}{{build="{build}"}} 1\n'


#: How long `/api/doctor` holds its report: the checks read the scheduler and run `git`.
_CONTRACT_TTL_S = 60


def _cached(
    read: Callable[[], dict[str, Any]], ttl: float, clock: Callable[[], float] = time.monotonic
) -> Callable[[], dict[str, Any]]:
    """`read`, asked at most once in `ttl` seconds; the page that asks while it is stale waits for the fresh read."""
    held: tuple[float, dict[str, Any]] | None = None
    lock = threading.Lock()

    def get() -> dict[str, Any]:
        nonlocal held
        with lock:
            if held is None or clock() - held[0] >= ttl:
                held = (clock(), read())
            return held[1]

    return get


class _Body:
    """A request's body, read by a worker thread only as much as a route asks for: a push over its limit is refused
    without the body being taken off the wire."""

    def __init__(self, request: Incoming) -> None:
        self._chunks = request.stream()
        self._held = bytearray()

    async def _read(self, size: int) -> bytes:
        while len(self._held) < size and (chunk := await anext(self._chunks, b"")):
            self._held += chunk
        taken = bytes(self._held[:size])
        del self._held[:size]
        return taken

    def __call__(self, size: int) -> bytes:
        return from_thread.run(self._read, size) if size > 0 else b""


class _Build(StaticFiles):
    """The build's files; one under `/assets/` is kept by the browser for good."""

    def file_response(
        self, full_path: os.PathLike[str] | str, stat_result: os.stat_result, scope: Scope, status_code: int = 200
    ) -> Reply:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if scope["path"].startswith(_ASSETS):
            response.headers["cache-control"] = _KEPT
        return response


class _Gated:
    """Answers or admits each request before any route sees it, whatever its method and path."""

    def __init__(self, app: ASGIApp, gate: Callable[[GateRequest], bool], workers: CapacityLimiter) -> None:
        self.app, self._gate, self._workers = app, gate, workers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            refused = await to_thread.run_sync(
                self._refusal, Incoming(scope), abandon_on_cancel=True, limiter=self._workers
            )
            if refused is not None:
                await refused(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _refusal(self, request: Incoming) -> Reply | None:
        """The gate's answer when it refuses the request, or None when it admits it."""
        query = request.url.query
        asked = GateRequest(request.method, _target(request) + (f"?{query}" if query else ""), request.headers)
        if self._gate(asked):
            return None
        answer = Reply(asked.wfile.getvalue(), asked.status)
        answer.raw_headers = [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in asked.sent]
        return answer


class _Events(StreamingResponse):
    """An open stream's response: the frames the page reads, until it leaves or the server ends the stream."""

    def __init__(self, app: PageApp, stream: Stream) -> None:
        super().__init__(app.pump(stream.frames), headers=_EVENT_HEADERS)
        self._app = app
        self._stream = stream

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with contextlib.suppress(ValueError):  # a frame still being made on an abandoned thread: its generator is
                self._stream.frames.close()  # closed once that frame is dropped
            self._stream.release()
            self._app.closed_stream()


_EVENT_HEADERS = {"content-type": "text/event-stream", "cache-control": "no-store"}

Endpoint = Callable[[Incoming], Awaitable[Reply]]
Work = Callable[[Incoming, Arrival, _Body], Reply]


class PageApp:
    """The ASGI app of the page: `routes` answer reads, `writes` answer changes, `streams` open the event streams and
    the rest is the build's static files. `gate`, when set, answers or admits each request before any route sees it."""

    def __init__(
        self,
        routes: ReadRoutes,
        writes: WriteRoutes,
        streams: Streams,
        snapshots: SnapshotCache,
        static: Path,
        flows: Collection[str],
        gate: Callable[[GateRequest], bool] | None = None,
        grpc: ASGIApp | None = None,
    ) -> None:
        self._routes, self._snapshots = routes, snapshots
        self._grpc = grpc
        self._flows = flows
        self._files = _Build(directory=static, check_dir=False)
        self._workers = CapacityLimiter(REQUEST_THREADS)
        self._frames = CapacityLimiter(
            math.inf
        )  # a stream's wait for its next frame is a thread the limit above counts
        self._lock = threading.Lock()
        self.open_streams = 0  # streams open
        self._scopes: set[CancelScope] = set()  # the wait for a frame of each stream open, so a stop can end it
        self._ending = False
        self._pending = (
            0  # requests the app has taken and not yet started answering; `end_streams` ends a stream among them
        )
        self._quiet = asyncio.Event()
        self._quiet.set()
        # In match order: a ledger's stream before the ledger's read, and the files last, since a request a route
        # matches by path alone is that route's 405 only while no later route matches it in full.
        table = [
            *(Route(path, self._streamed(handler), methods=["GET"]) for path, handler in streams.routes()),
            *(Route(path, self._read(handler), methods=["GET"]) for path, handler in routes.routes()),
            *(Route(path, self._written(handler), methods=list(methods)) for path, methods, handler in writes.routes()),
            *(Route(path, self._page, methods=["GET"]) for path in _PAGES),
            Route("/flow/{flow}", self._flow, methods=["GET"]),
            Route("/{path:served}", self._file, methods=["GET"]),
        ]
        gated = [] if gate is None else [Middleware(_Gated, gate=gate, workers=self._workers)]
        self._app = Starlette(routes=table, middleware=[Middleware(Gzip), *gated])

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        self._pending += 1  # from the app's entry: a request taken before its endpoint holds a stop open too
        self._quiet.clear()
        held = True

        def started() -> None:
            # a response's start is what a stop waits for; a stream's body goes on after it, as before the count moved
            nonlocal held
            if held:
                held = False
                self._pending -= 1
                if not self._pending:
                    self._quiet.set()

        try:
            await self._answer(scope, receive, send, started)
        finally:
            started()

    async def _answer(
        self, scope: MutableMapping[str, Any], receive: Any, send: Any, started: Callable[[], None]
    ) -> None:
        if self._grpc is not None and scope["path"].startswith(CLOUDEVENTS_GRPC_PATH):
            await self._grpc(scope, receive, send)  # its own token, so no gate; a gRPC body is read by the handler
            return
        body_done, dropping = False, None

        async def counted() -> MutableMapping[str, Any]:
            nonlocal body_done
            message = await receive()
            body_done = message["type"] != "http.request" or not message.get("more_body", False)
            return message

        async def drop() -> None:
            while not body_done:
                await counted()

        async def answering(message: MutableMapping[str, Any]) -> None:
            nonlocal dropping
            if message["type"] == "http.response.start" and not body_done and dropping is None:
                dropping = asyncio.ensure_future(drop())  # a body left unread stalls Hypercorn's end of the response
            await send(message)
            if message["type"] == "http.response.start":
                started()

        try:
            await self._app(scope, counted, answering)
        finally:
            if dropping is not None:
                await dropping

    async def end_streams(self) -> None:
        """End every open stream and refuse a new one: a stopping server has no stream to wait for."""
        self._ending = True
        for scope in list(self._scopes):
            scope.cancel()

    async def drained(self, timeout: float) -> bool:
        """Wait up to `timeout` seconds for every request being answered to be done; whether they all were."""
        try:
            await asyncio.wait_for(self._quiet.wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def pump(self, frames: Any) -> AsyncIterator[bytes]:
        """`frames` as they are made, each wait on a thread of its own: it ends with the stream or on a stop."""
        while not self._ending:
            with CancelScope() as waiting:
                self._scopes.add(waiting)
                try:
                    frame = await to_thread.run_sync(next, frames, None, abandon_on_cancel=True, limiter=self._frames)
                finally:
                    self._scopes.discard(waiting)
            if waiting.cancelled_caught or frame is None:
                return
            yield frame

    def closed_stream(self) -> None:
        with self._lock:
            self.open_streams -= 1

    def _admit(self) -> bool:
        with self._lock:
            if self.open_streams >= STREAM_LIMIT:
                return False
            self.open_streams += 1
            return True

    async def _worker(self, request: Incoming, work: Work) -> Reply:
        """Run `work` for `request` on a worker thread; a body its model refuses is a logged 500, since the page reads only
        what a model names."""
        arrival = Arrival(
            time.monotonic(), self._workers.borrowed_tokens + 1, self.open_streams
        )  # busy counts this request
        body = _Body(request)

        def run() -> Reply:
            try:
                return work(request, arrival, body)
            except ClientDisconnect:
                return Reply(status_code=400)  # the client left mid-body; nobody reads this
            except ValidationError:
                logger.exception("StarPulse: %s %s built a body its model refuses", request.method, request.url.path)
                error = encode("error", {"error": "the server built a body its contract refuses"})
                return self._json(request, Response(error, 500))

        return await to_thread.run_sync(run, abandon_on_cancel=True, limiter=self._workers)

    def _read(self, handler: Handler) -> Endpoint:
        def read(request: Incoming, arrival: Arrival, body: _Body) -> Reply:
            queued_s = time.monotonic() - arrival.at
            asked = Request(_target(request), request.url.query, _client(request))
            with self._routes.watch(asked, queued_s, arrival) as timing:
                response = handler(asked)
                timing.computed()
                return self._json(request, response)

        return self._endpoint(read)

    def _written(self, handler: WriteHandler) -> Endpoint:
        def write(request: Incoming, arrival: Arrival, body: _Body) -> Reply:
            asked = WriteRequest(request.method, _target(request), _client(request), request.headers, body)
            response = handler(asked)
            if response is None:
                return _not_found()  # a push this deployment leaves unconfigured
            reply = self._json(request, response)
            self._snapshots.require_current()  # a write is answered once the snapshot read after it holds what it published
            return reply

        return self._endpoint(write)

    def _streamed(self, handler: StreamHandler) -> Endpoint:
        def open_stream(request: Incoming, arrival: Arrival, body: _Body) -> Reply:
            asked = Request(_target(request), request.url.query, _client(request))
            took = False

            def admit() -> bool:
                nonlocal took
                took = self._admit()
                return took

            try:
                stream = handler(asked, admit)
            except BaseException:
                if took:
                    self.closed_stream()
                raise
            if isinstance(stream, Stream):
                return _Events(self, stream)
            if took:  # admitted, then refused (a ledger that does not exist)
                self.closed_stream()
            return self._json(request, stream)

        opening = self._endpoint(open_stream)

        async def endpoint(request: Incoming) -> Reply:
            if request.method == "HEAD":
                return Reply(headers=_EVENT_HEADERS)  # the headers a GET sends, without opening a stream
            return await opening(request)

        return endpoint

    def _endpoint(self, work: Work) -> Endpoint:
        async def endpoint(request: Incoming) -> Reply:
            return await self._worker(request, work)

        return endpoint

    async def _page(self, request: Incoming) -> Reply:
        return await self._files.get_response("index.html", request.scope)

    async def _flow(self, request: Incoming) -> Reply:
        flow = request.path_params["flow"]
        if flow == "board" or flow not in self._flows:
            return _not_found()
        return await self._page(request)

    async def _file(self, request: Incoming) -> Reply:
        return await self._files.get_response(request.path_params["path"], request.scope)

    def _json(self, request: Incoming, response: Response) -> Reply:
        """`response` as it says: JSON unless told otherwise; an `Encoded` body is sent as the gzip it already holds to a
        page that accepts gzip, and any other is left to the `Gzip` middleware."""
        body, status, cache, content_type, retry_after, close = response
        headers = {"content-type": content_type, "cache-control": cache}
        if isinstance(body, Encoded):
            gzipped = body.gzipped if accepts_gzip(request.headers.get("accept-encoding")) else None
            body = body.body if gzipped is None else gzipped
            if gzipped is not None:
                headers["content-encoding"] = "gzip"
        if retry_after is not None:
            headers["retry-after"] = str(retry_after)
        if close and request.scope["http_version"] != "2":  # HTTP/2 has no connection header, and a stream ends alone
            headers["connection"] = "close"
        if request.method == "HEAD":
            return Reply(b"", status, headers | {"content-length": str(len(body))})
        return Reply(body, status, headers)


def _target(request: Incoming) -> str:
    """The path as the client sent it, still percent-encoded: a route decodes what it takes from it."""
    raw = request.scope.get("raw_path")
    return raw.decode("ascii", "replace") if raw else request.scope["path"]


def _client(request: Incoming) -> str:
    return request.client.host if request.client else ""


def _not_found() -> Reply:
    return PlainTextResponse("Not Found", 404)


def page_app(
    feed: BoardFeed,
    static: Path,
    history: History,
    window: HistoryWindow,
    board: Board,
    services: Services = Services(),
    clock: Callable[[], float] = time.time,
    gate: Callable[[GateRequest], bool] | None = None,
) -> PageApp:
    services = replace(services, harnesses=services.harnesses or Harnesses((), {}))
    snapshots = SnapshotCache(feed)
    routes = ReadRoutes(
        feed, history, snapshots, window, board, services, clock=clock, page_gauge=lambda: build_gauge(static)
    )
    writes = WriteRoutes(feed, window, board, services)

    def build_frame() -> str | None:
        build = page_build(static)
        return None if build is None else _build_text(build)

    streams = Streams(feed, snapshots, build_frame)
    grpc = None if services.events is None else cloudevents_grpc(services.events)
    return PageApp(routes, writes, streams, snapshots, static, feed.machines.keys(), gate, grpc)
