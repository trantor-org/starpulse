"""The page as an ASGI app: the page and its assets, the event streams and every `/api` route.

Each request runs its (blocking) routes on a worker thread, so the routes stay plain functions of a request; a stream
hands its frames to the event loop one at a time. A server such as Hypercorn runs the app, over HTTP/1.1 or HTTP/2.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import gzip
import hashlib
import logging
import math
import mimetypes
import threading
import time
from collections.abc import AsyncIterator, Callable, Collection, MutableMapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anyio import CancelScope, CapacityLimiter, from_thread, to_thread
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect
from starlette.requests import Request as Incoming
from starlette.responses import FileResponse, PlainTextResponse, StreamingResponse
from starlette.responses import Response as Reply
from starlette.routing import Route

from starpulse.harness_telemetry.harnesses import Harnesses
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.model.seam import Board
from starpulse.runs.cloudevents_grpc import PATH as CLOUDEVENTS_GRPC_PATH
from starpulse.runs.cloudevents_grpc import cloudevents_grpc
from starpulse.views.compression import LEVEL, Encoded, accepts_gzip, compressed, gzip_frames
from starpulse.views.encoding import encode, event
from starpulse.views.gate_request import GateRequest
from starpulse.views.reads import Arrival, ReadRoutes, Request, Response
from starpulse.views.routes import _PAGES
from starpulse.views.services import Services
from starpulse.views.snapshot_cache import SnapshotCache
from starpulse.views.streams import Stream, Streams
from starpulse.views.write_routes import WriteRequest, WriteRoutes

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starlette.types import ASGIApp

    from starpulse.board.board_feed import BoardFeed
    from starpulse.flow_metrics.history import History


logger = logging.getLogger(__name__)


#: Requests answered at once, each on a worker thread; the next waits for one to finish.
REQUEST_THREADS = 128

#: Streams open at once; a stream past the limit is refused with a 503.
STREAM_LIMIT = 256


#: The Vite build names every file under it by its content's digest, so a new build never reuses a name.
_ASSETS = "/assets/"


_KEPT = "public, max-age=31536000, immutable"


#: The static files worth gzipping: the build's text. Its images and fonts are already compressed.
_TEXT = (".html", ".js", ".mjs", ".css", ".svg", ".json", ".map")


#: The page's scripts are `text/javascript` on every host: the host's MIME table may call them `application/javascript`.
_SCRIPTS = {".js": "text/javascript", ".mjs": "text/javascript"}


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


@functools.lru_cache(maxsize=64)
def _gzipped(path: str, mtime_ns: int) -> bytes:
    """A static file gzipped once per build: `mtime_ns` keys a rebuilt file afresh."""
    return gzip.compress(Path(path).read_bytes(), compresslevel=LEVEL, mtime=0)


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


#: Every method reaches the gate, which answers each before any route does; only the five it serves go further.
_METHODS = ("GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE")


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


class _Events(StreamingResponse):
    """An open stream's response: the frames the page reads, until it leaves or the server ends the stream."""

    def __init__(self, app: PageApp, stream: Stream, gzipped: bool) -> None:
        headers = {"content-type": "text/event-stream", "cache-control": "no-store"}
        if gzipped:
            headers["content-encoding"] = "gzip"
        super().__init__(app.pump(stream.frames, gzip_frames() if gzipped else None), headers=headers)
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
        self._routes, self._writes, self._streams, self._snapshots = routes, writes, streams, snapshots
        self._grpc = grpc
        self._static, self._flows, self._gate = static, flows, gate
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
        self._app = Starlette(routes=[Route("/{path:path}", self._endpoint, methods=list(_METHODS))])

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

    async def pump(self, frames: Any, compress: Callable[[bytes], bytes] | None) -> AsyncIterator[bytes]:
        """`frames` as they are made, each wait on a thread of its own: it ends with the stream or on a stop."""

        def step() -> bytes | None:
            frame = next(frames, None)
            return frame if frame is None or compress is None else compress(frame)

        while not self._ending:
            with CancelScope() as waiting:
                self._scopes.add(waiting)
                try:
                    frame = await to_thread.run_sync(step, abandon_on_cancel=True, limiter=self._frames)
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

    async def _endpoint(self, request: Incoming) -> Reply:
        arrival = Arrival(
            time.monotonic(), self._workers.borrowed_tokens + 1, self.open_streams
        )  # busy counts this request
        return await to_thread.run_sync(
            self._respond, request, arrival, _Body(request), abandon_on_cancel=True, limiter=self._workers
        )

    def _respond(self, request: Incoming, arrival: Arrival, body: _Body) -> Reply:
        """Answer one request on a worker thread; a body its model refuses is a logged 500, since the page reads only
        what a model names."""
        queued_s = time.monotonic() - arrival.at
        try:
            if (refused := self._gated(request)) is not None:
                return refused
            if request.method not in ("GET", "HEAD", "POST", "PUT", "DELETE"):
                return Reply(status_code=501)  # the gate has answered it first, as it answers every method
            if request.method in ("POST", "PUT", "DELETE"):
                return self._write(request, body)
            return self._get(request, queued_s, arrival)
        except ClientDisconnect:
            return Reply(status_code=400)  # the client left mid-body; nobody reads this
        except ValidationError:
            logger.exception("StarPulse: %s %s built a body its model refuses", request.method, request.url.path)
            error = encode("error", {"error": "the server built a body its contract refuses"})
            return self._json(request, Response(error, 500))

    def _gated(self, request: Incoming) -> Reply | None:
        """The gate's answer when it refuses the request, or None when it admits it."""
        if self._gate is None:
            return None
        query = request.url.query
        asked = GateRequest(request.method, _target(request) + (f"?{query}" if query else ""), request.headers)
        if self._gate(asked):
            return None
        answer = Reply(asked.wfile.getvalue(), asked.status)
        answer.raw_headers = [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in asked.sent]
        return answer

    def _get(self, request: Incoming, queued_s: float, arrival: Arrival) -> Reply:
        path = _target(request)
        if request.method == "HEAD":
            return self._page(request, path)
        read = Request(path, request.url.query, _client(request))
        took = False

        def admit() -> bool:
            nonlocal took
            took = self._admit()
            return took

        try:
            stream = self._streams(read, admit)
        except BaseException:
            if took:
                self.closed_stream()
            raise
        if isinstance(stream, Stream):
            return _Events(self, stream, accepts_gzip(request.headers.get("accept-encoding")))
        if took:  # admitted, then refused (a ledger that does not exist)
            self.closed_stream()
        if stream is not None:
            return self._json(request, stream)
        with self._routes.watch(read, queued_s, arrival) as timing:
            response = self._routes(read)
            timing.computed()
            if response is not None:
                return self._json(request, response)
        return self._page(request, path)

    def _write(self, request: Incoming, body: _Body) -> Reply:
        """Answer a write through `writes`; a method and path it does not name are a 404."""
        write = WriteRequest(request.method, _target(request), _client(request), request.headers, body)
        response = self._writes(write)
        return _not_found() if response is None else self._json(request, response)

    def _page(self, request: Incoming, path: str) -> Reply:
        if self._writes.post_only(path):
            return Reply(status_code=405, headers={"allow": "POST"})
        if path in _PAGES or path.startswith("/flow/") and path[6:] in self._flows - {"board"}:
            return self._file(request, path, "/index.html")
        return self._file(request, path, request.scope["path"])

    def _file(self, request: Incoming, path: str, name: str) -> Reply:
        """The static file `name` names, gzipped when it is text and the page accepts gzip; `path` is the request's."""
        file = self._static.joinpath(*(part for part in name.split("/") if part not in ("", ".", "..")))
        try:
            stat = file.stat()
        except OSError:
            return _not_found()
        if not file.is_file():
            return _not_found()
        headers = {
            "content-type": _SCRIPTS.get(file.suffix.lower())
            or mimetypes.guess_type(file.name)[0]
            or "application/octet-stream"
        }
        if path.startswith(_ASSETS):
            headers["cache-control"] = _KEPT
        if file.name.endswith(_TEXT) and accepts_gzip(request.headers.get("accept-encoding")):
            headers |= {"content-encoding": "gzip", "vary": "Accept-Encoding"}
            return Reply(_gzipped(str(file), stat.st_mtime_ns), headers=headers)
        return FileResponse(file, headers=headers, stat_result=stat)

    def _json(self, request: Incoming, response: Response) -> Reply:
        """`response` as it says: JSON unless told otherwise; an `Encoded` body is sent as the gzip it already holds to a
        page that accepts gzip."""
        body, status, cache, content_type, retry_after, close = response
        accepted = request.headers.get("accept-encoding")
        if isinstance(body, Encoded):
            body, gzipped = body.body, body.gzipped if accepts_gzip(accepted) else None
        else:
            gzipped = compressed(body, accepted)
        headers = {"content-type": content_type, "cache-control": cache}
        if retry_after is not None:
            headers["retry-after"] = str(retry_after)
        if gzipped is not None:
            body = gzipped
            headers["content-encoding"] = "gzip"
        if close and request.scope["http_version"] != "2":  # HTTP/2 has no connection header, and a stream ends alone
            headers["connection"] = "close"
        if request.method != "GET":
            self._snapshots.require_current()  # a write is answered once the snapshot read after it holds what it published
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
