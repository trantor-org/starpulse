"""The page as an ASGI app: the page and its assets, the `/graphql` subscriptions and every `/api` route.

Each handler is a Starlette route and runs (blocking) on a worker thread, so the handlers stay plain functions of a
request; a stream hands its frames to the event loop one at a time. A server such as Hypercorn runs the app, over
HTTP/1.1 or HTTP/2.
"""

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
from opentelemetry import trace
from opentelemetry.trace import SpanKind
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
from starpulse.event_log.caught_up import CaughtUp
from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.runs.adapters.inbound.cloudevents_grpc import PATH as CLOUDEVENTS_GRPC_PATH
from starpulse.runs.adapters.inbound.cloudevents_grpc import cloudevents_grpc
from starpulse.views.adapters.inbound.api import graphql, intake, metrics
from starpulse.views.adapters.inbound.api.answering import CAUGHT_UP_S, PLACE, RAN, WORKERS
from starpulse.views.adapters.inbound.api.openapi import swagger
from starpulse.views.adapters.inbound.api.routing import Api, api_routes
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.compression import Gzip
from starpulse.views.adapters.inbound.snapshots import Snapshots
from starpulse.views.adapters.outbound import request_durations
from starpulse.views.model.encoding import encode
from starpulse.views.ports.services import Services

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starlette.types import ASGIApp, Receive, Scope, Send

    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.flow_metrics.adapters.outbound.history import HistoryStore


logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("starpulse")


#: Requests answered at once, each on a worker thread; the next waits for one to finish.
REQUEST_THREADS = 128

#: Further threads that only the board's own reads and writes (see `_light`) run on once the pool above is full, so
#: a pool held by slow heavy reads still answers the snapshot, a task read, a write and the metrics scrape.
RESERVE_THREADS = 16

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


class _Build(StaticFiles):
    """The build's files; one under `/assets/` is kept by the browser for good."""

    def file_response(
        self, full_path: os.PathLike[str] | str, stat_result: os.stat_result, scope: Scope, status_code: int = 200
    ) -> Reply:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if scope["path"].startswith(_ASSETS):
            response.headers["cache-control"] = _KEPT
        return response


class _CaughtUp:
    """Applies what the workers keep in the log before a request under `/api`, or to `/graphql`, reads it, so no follower thread does."""

    def __init__(self, app: ASGIApp, caught_up: CaughtUp, workers: CapacityLimiter) -> None:
        self.app, self._caught_up, self._workers = app, caught_up, workers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        reads = scope["type"] == "http" and (scope["path"].startswith("/api/") or scope["path"] == "/graphql")
        if reads and self._caught_up.due():
            started = time.monotonic()
            await to_thread.run_sync(self._caught_up, abandon_on_cancel=True, limiter=scope.get(WORKERS, self._workers))
            scope[CAUGHT_UP_S] = time.monotonic() - started
        await self.app(scope, receive, send)


_BUSY_RETRY_S = 1

#: Seconds between the log lines that say what held the workers while requests were refused.
_BUSY_LOG_S = 10.0


def _light(scope: Scope) -> bool:
    """Whether the request is one of the board's own reads and writes, which hold a thread only for a moment: the
    snapshot, a task read, any write under `/api`, the metrics scrape and an intake post."""
    path, method = scope["path"], scope["method"]
    return (
        path in ("/metrics", "/api/snapshot")
        or path.startswith("/intake/")
        or (path.startswith("/api/") and (path.startswith("/api/task/") or method in ("POST", "PUT", "DELETE")))
    )


def _kind(scope: Scope) -> str:
    """The method and the first two path segments, so a count by kind holds no id and a hostile path forges no log line."""
    segments = "/".join(scope["path"].split("/")[1:3])
    return f"{scope['method']} /{ascii(segments)[1:-1]}"


class _Inflight:
    """The requests being answered, counted by kind, so a refusal can say what held the workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._logged = float("-inf")

    def enter(self, kind: str) -> None:
        with self._lock:
            self._counts[kind] = self._counts.get(kind, 0) + 1

    def leave(self, kind: str) -> None:
        with self._lock:
            if self._counts[kind] == 1:
                del self._counts[kind]
            else:
                self._counts[kind] -= 1

    def refused(self, scope: Scope) -> None:
        """Log what is in flight, at most once in `_BUSY_LOG_S`."""
        with self._lock:
            now = time.monotonic()
            if now - self._logged < _BUSY_LOG_S:
                return
            self._logged = now
            held = sorted(self._counts.items(), key=lambda kv: -kv[1])
        logger.warning(
            "request workers busy: refused %s with %d in flight: %s",
            _kind(scope),
            sum(count for _, count in held),
            ", ".join(f"{kind}={count}" for kind, count in held),
        )


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
    """Refuses a request with a 503 while no request worker is free, except a `_light` one, which runs on the reserve
    while it has a thread; gives each request the `_Place` its stream would take, which it gives back whenever the
    request ends, and counts the requests in flight by kind."""

    def __init__(
        self,
        app: ASGIApp,
        workers: CapacityLimiter,
        reserve: CapacityLimiter,
        streams: _Streams,
        inflight: _Inflight,
    ) -> None:
        self.app, self._workers, self._reserve, self._streams, self._inflight = app, workers, reserve, streams, inflight

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        pool = self._workers
        if not pool.available_tokens and _light(scope):
            pool = self._reserve
        if not pool.available_tokens:
            self._inflight.refused(scope)
            busy = encode("error", {"error": "too many requests in flight; retry shortly"})
            headers = {"content-type": "application/json", "cache-control": "no-store"}
            await Reply(busy, 503, {**headers, "retry-after": str(_BUSY_RETRY_S)})(scope, receive, send)
            return
        place = scope[PLACE] = _Place(self._streams)
        scope[WORKERS] = pool
        kind = _kind(scope)
        self._inflight.enter(kind)
        try:
            await self.app(scope, receive, send)
        finally:
            self._inflight.leave(kind)
            place.give()


class _Traced:
    """Opens a server span for each request of its route, from the request's arrival to the last byte sent, and gives
    it the queue (the wait for a worker thread), compute (the answer built) and write (the answer sent) it passed
    through as children."""

    def __init__(self, app: ASGIApp, route: str, workers: CapacityLimiter, streams: _Streams) -> None:
        self.app, self._route, self._workers, self._streams = app, route, workers, streams

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        arrived = time.time_ns()
        marks: dict[str, int] = {}
        scope[RAN] = lambda: marks.setdefault("ran", time.time_ns())
        method = scope["method"]
        attributes = {
            "http.request.method": method,
            "http.route": self._route,
            "starpulse.workers_busy": self._workers.borrowed_tokens + 1,  # this one is busy
            "starpulse.streams_open": self._streams.open,
        }
        with _tracer.start_as_current_span(
            f"{method} {self._route}", kind=SpanKind.SERVER, start_time=arrived, attributes=attributes
        ) as span:
            if CAUGHT_UP_S in scope:
                span.set_attribute("starpulse.caught_up_s", scope[CAUGHT_UP_S])

            async def answering(message: MutableMapping[str, Any]) -> None:
                if message["type"] == "http.response.start":
                    marks["computed"] = time.time_ns()
                    span.set_attribute("http.response.status_code", message["status"])
                await send(message)

            try:
                await self.app(scope, receive, answering)
            finally:  # a write that fails on a closed socket is the slow one most worth the span
                ran, computed, ended = marks.get("ran"), marks.get("computed"), time.time_ns()
                for phase, began, finished in (("queue", arrived, ran), ("compute", ran, computed), ("write", computed, ended)):
                    if began is not None and finished is not None:
                        _tracer.start_span(phase, start_time=began).end(end_time=finished)


class _Observed:
    """Observes each read of its route in `starpulse_request_duration_seconds`, from the request's arrival to the last
    byte sent."""

    def __init__(self, app: ASGIApp, route: str, params: frozenset[str]) -> None:
        self.app, self._route, self._params = app, route, params

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = time.monotonic()
        client = next((value.decode("latin-1") for key, value in scope["headers"] if key == b"x-starpulse-client"), "")
        try:
            await self.app(scope, receive, send)
        finally:
            seconds = time.monotonic() - started
            request_durations.observe(self._route, self._params, scope.get("query_string", b""), client, seconds)


class PageApp:
    """The ASGI app of the page: `api` are the routes under `/api` (one module a resource, mounted together), `metrics`
    the routes beside them (the scrape and the intake) and the rest is the build's static files."""

    def __init__(
        self,
        api: list[ApiRoute],
        metrics: list[ApiRoute],
        static: Path,
        flows: Collection[str],
        grpc: ASGIApp | None = None,
        seams: Api | None = None,
        caught_up: CaughtUp | None = None,
    ) -> None:
        self._grpc = grpc
        self._flows = flows
        self._files = _Build(directory=static, check_dir=False)
        self._workers = CapacityLimiter(REQUEST_THREADS)
        self._reserve = CapacityLimiter(RESERVE_THREADS)
        self._inflight = _Inflight()
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
        # In match order: `/api`, `/metrics` and `/intake` first, the pages, and the files last, since a request a route matches
        # by path alone is that route's 405 only while no later route matches it in full.
        table = [
            Mount("/api", routes=[self._route(route, "/api") for route in api]),
            *(self._route(route, "") for route in metrics),
            *(Route(path, self._page, methods=["GET"]) for path in ("/", "/board", "/runs")),
            Route("/swagger", swagger, methods=["GET"]),
            Route("/flow/{flow}", self._flow, methods=["GET"]),
            Route("/{path:served}", self._file, methods=["GET"]),
        ]
        admitted = Middleware(
            _Admitted, workers=self._workers, reserve=self._reserve, streams=self._streams, inflight=self._inflight
        )
        fresh = [] if caught_up is None else [Middleware(_CaughtUp, caught_up=caught_up, workers=self._workers)]
        self._app = Starlette(routes=table, middleware=[Middleware(Gzip), admitted, *fresh])
        self._app.state.api = seams  # what the read endpoints take their seams from
        self._app.state.workers = self._workers  # and the threads they run on
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
            await self._grpc(scope, receive, send)  # its own token; a gRPC body is read by the handler
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
            # adr-exempt: handshake
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

    def _route(self, route: ApiRoute, prefix: str) -> Route:
        """`route` as a Starlette route at its own path; each request but a stream's is a span, and a read is observed
        in the request-duration histogram, under `prefix` and its path template."""
        at = route.path
        traced = Middleware(_Traced, route=prefix + at, workers=self._workers, streams=self._streams)
        match route:
            case ReadRoute(_, handler, params):
                observed = Middleware(_Observed, route=prefix + at, params=params)
                return Route(at, handler, methods=["GET"], middleware=[observed, traced])
            case WriteRoute(_, methods, handler):
                return Route(at, handler, methods=list(methods), middleware=[traced])

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
    snapshots: Snapshots,
    static: Path,
    history: HistoryStore,
    window: HistoryWindow,
    board: Board,
    services: Services = Services(),
    clock: Callable[[], float] = time.time,
    caught_up: CaughtUp | None = None,
) -> PageApp:
    """The Page API over `feed`, serving the snapshot and deltas the Board writer stored (`snapshots`)."""
    services = replace(services, harnesses=services.harnesses or Harnesses((), {}))

    api = Api(
        feed,
        history,
        snapshots,
        window,
        board,
        services,
        clock=clock,
        build=lambda: page_build(static),
        page_gauge=lambda: build_gauge(static),
    )
    grpc = None if services.events is None else cloudevents_grpc(services.events)
    return PageApp(
        api_routes(api),
        [*metrics.routes, *graphql.routes, *intake.routes],
        static,
        feed.machines.keys(),
        grpc,
        api,
        caught_up,
    )
