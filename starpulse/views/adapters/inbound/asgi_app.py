"""The page as an ASGI app: the page and its assets, the event streams and every `/api` route.

Each handler is a Starlette route and runs (blocking) on a worker thread, so the handlers stay plain functions of a
request; a stream hands its frames to the event loop one at a time. A server such as Hypercorn runs the app, over
HTTP/1.1 or HTTP/2.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import math
import mimetypes
import os
import threading
import time
from collections.abc import AsyncIterator, Callable, Collection, MutableMapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anyio import CancelScope, CapacityLimiter, to_thread
from starlette.applications import Starlette
from starlette.convertors import PathConvertor, register_url_convertor
from starlette.middleware import Middleware
from starlette.requests import Request as Incoming
from starlette.responses import PlainTextResponse
from starlette.responses import Response as Reply
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.model.seam import Board
from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.runs.adapters.inbound.cloudevents_grpc import PATH as CLOUDEVENTS_GRPC_PATH
from starpulse.runs.adapters.inbound.cloudevents_grpc import cloudevents_grpc
from starpulse.views.adapters.inbound.api import metrics
from starpulse.views.adapters.inbound.api.answering import PLACE, RAN, target
from starpulse.views.adapters.inbound.api.routing import Api, api_routes
from starpulse.views.adapters.inbound.api.table import ApiRoute, Arrival, ReadRoute, StreamRoute, Watch, WriteRoute
from starpulse.views.adapters.inbound.compression import Gzip
from starpulse.views.adapters.inbound.gate_request import GateRequest
from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache
from starpulse.views.model.encoding import encode, event
from starpulse.views.ports.services import Services

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
        asked = GateRequest(request.method, target(request) + (f"?{query}" if query else ""), request.headers)
        if self._gate(asked):
            return None
        answer = Reply(asked.wfile.getvalue(), asked.status)
        answer.raw_headers = [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in asked.sent]
        return answer


_BUSY_RETRY_S = 1


class _Streams:
    """The streams open, at most `STREAM_LIMIT`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.open = 0

    def take(self) -> bool:
        with self._lock:
            if self.open >= STREAM_LIMIT:
                return False
            self.open += 1
            return True

    def give(self) -> None:
        with self._lock:
            self.open -= 1


class _Place:
    """One request's place among the streams open: taken when its handler admits it, given back once when the request
    ends, and never taken after that, so a handler left running on an abandoned thread cannot leak it."""

    def __init__(self, streams: _Streams) -> None:
        self._streams = streams
        self._lock = threading.Lock()
        self._taken = False
        self._ended = False

    def take(self) -> bool:
        with self._lock:
            if self._ended:
                return False
            if not self._taken:
                self._taken = self._streams.take()
            return self._taken

    def give(self) -> None:
        with self._lock:
            self._ended = True
            if self._taken:
                self._taken = False
                self._streams.give()


class _Admitted:
    """Refuses every request with a 503 while no request worker is free, and gives each request the `_Place` its stream
    would take, which it gives back whenever the request ends."""

    def __init__(self, app: ASGIApp, workers: CapacityLimiter, streams: _Streams) -> None:
        self.app, self._workers, self._streams = app, workers, streams

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not self._workers.available_tokens:
            busy = encode("error", {"error": "too many requests in flight; retry shortly"})
            headers = {"content-type": "application/json", "cache-control": "no-store"}
            await Reply(busy, 503, {**headers, "retry-after": str(_BUSY_RETRY_S)})(scope, receive, send)
            return
        place = scope[PLACE] = _Place(self._streams)
        try:
            await self.app(scope, receive, send)
        finally:
            place.give()


class _Timed:
    """Times each read of its route with its `Watch`, from the request's arrival to the last byte sent."""

    def __init__(self, app: ASGIApp, watch: Watch, workers: CapacityLimiter, streams: _Streams) -> None:
        self.app, self._watch, self._workers, self._streams = app, watch, workers, streams

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Incoming(scope)
        arrival = Arrival(
            time.monotonic(), self._workers.borrowed_tokens + 1, self._streams.open
        )  # busy counts this one
        with self._watch(request, arrival) as timing:
            scope[RAN] = timing.ran

            async def answering(message: MutableMapping[str, Any]) -> None:
                if message["type"] == "http.response.start":
                    timing.computed()
                await send(message)

            await self.app(scope, receive, answering)


class PageApp:
    """The ASGI app of the page: `api` are the routes under `/api` (one module a resource, mounted together), `metrics`
    the route beside them and the rest is the build's static files. `gate`, when set, answers or admits each request
    before any route sees it."""

    def __init__(
        self,
        api: list[ApiRoute],
        metrics: list[ApiRoute],
        snapshots: SnapshotCache,
        static: Path,
        flows: Collection[str],
        gate: Callable[[GateRequest], bool] | None = None,
        grpc: ASGIApp | None = None,
        seams: Api | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._grpc = grpc
        self._flows = flows
        self._files = _Build(directory=static, check_dir=False)
        self._workers = CapacityLimiter(REQUEST_THREADS)
        self._frames = CapacityLimiter(
            math.inf
        )  # a stream's wait for its next frame is a thread the limit above counts
        self._streams = _Streams()
        self._scopes: set[CancelScope] = set()  # the wait for a frame of each stream open, so a stop can end it
        self._ending = False
        self._pending = (
            0  # requests the app has taken and not yet started answering; `end_streams` ends a stream among them
        )
        self._quiet = asyncio.Event()
        self._quiet.set()
        # In match order: `/api` and `/metrics` first, the pages, and the files last, since a request a route matches
        # by path alone is that route's 405 only while no later route matches it in full.
        table = [
            Mount("/api", routes=[self._route(route) for route in api]),
            *(self._route(route, "/metrics") for route in metrics),
            *(Route(path, self._page, methods=["GET"]) for path in ("/", "/board", "/runs")),
            Route("/flow/{flow}", self._flow, methods=["GET"]),
            Route("/{path:served}", self._file, methods=["GET"]),
        ]
        gated = [] if gate is None else [Middleware(_Gated, gate=gate, workers=self._workers)]
        admitted = Middleware(_Admitted, workers=self._workers, streams=self._streams)
        self._app = Starlette(routes=table, middleware=[Middleware(Gzip), admitted, *gated])
        self._app.state.api = seams  # what the read endpoints take their seams from
        self._app.state.workers = self._workers  # and the threads they run on
        self._app.state.snapshots = snapshots  # a write waits on these
        self._app.state.pump = self.pump  # and a stream writes its frames through this

    @property
    def open_streams(self) -> int:
        return self._streams.open

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

    def _route(self, route: ApiRoute, path: str | None = None) -> Route:
        """`route` as a Starlette route: at its own path, or at `path` where it is not under `/api`."""
        at = route.path if path is None else path
        match route:
            case ReadRoute(_, handler, watch):
                timed = (
                    []
                    if watch is None
                    else [Middleware(_Timed, watch=watch, workers=self._workers, streams=self._streams)]
                )
                return Route(at, handler, methods=["GET"], middleware=timed)
            case WriteRoute(_, methods, handler):
                return Route(at, handler, methods=list(methods))
            case StreamRoute(_, handler):
                return Route(at, handler, methods=["GET"])

    async def _page(self, request: Incoming) -> Reply:
        return await self._files.get_response("index.html", request.scope)

    async def _flow(self, request: Incoming) -> Reply:
        flow = request.path_params["flow"]
        if flow == "board" or flow not in self._flows:
            return _not_found()
        return await self._page(request)

    async def _file(self, request: Incoming) -> Reply:
        return await self._files.get_response(request.path_params["path"], request.scope)


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

    def build_frame() -> str | None:
        build = page_build(static)
        return None if build is None else _build_text(build)

    api = Api(
        feed,
        history,
        snapshots,
        window,
        board,
        services,
        clock=clock,
        build=build_frame,
        page_gauge=lambda: build_gauge(static),
    )
    grpc = None if services.events is None else cloudevents_grpc(services.events)
    return PageApp(api_routes(api), metrics.routes, snapshots, static, feed.machines.keys(), gate, grpc, api)
