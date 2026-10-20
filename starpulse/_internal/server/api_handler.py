"""The request handler: the page and its assets, the event streams and every `/api` route."""

from __future__ import annotations

import functools
import gzip
import hashlib
import io
import logging
import os
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from starpulse._internal.board.seam import Board
from starpulse._internal.config.harnesses import Harnesses
from starpulse._internal.feed.history_window import HistoryWindow
from starpulse._internal.server.compression import LEVEL, Encoded, accepts_gzip, compressed, gzip_stream
from starpulse._internal.server.encoding import encode, event
from starpulse._internal.server.reads import Arrival, ReadRoutes, Request, Response
from starpulse._internal.server.routes import _PAGES
from starpulse._internal.server.services import Services
from starpulse._internal.server.snapshot_cache import SnapshotCache
from starpulse._internal.server.streams import Stream, Streams
from starpulse._internal.server.write_routes import WriteRequest, WriteRoutes

if TYPE_CHECKING:  # annotation only: a runtime import would put the autopilot in the Delivery worker's import closure
    from starpulse._internal.eventlog.history import History
    from starpulse._internal.feed.board_feed import BoardFeed


logger = logging.getLogger(__name__)


#: Seconds a stream refused for a full stream pool is asked to wait before it reconnects.
_STREAM_RETRY_S = 5


#: The Vite build names every file under it by its content's digest, so a new build never reuses a name.
_ASSETS = "/assets/"


_KEPT = "public, max-age=31536000, immutable"


#: The static files worth gzipping: the build's text. Its images and fonts are already compressed.
_TEXT = (".html", ".js", ".mjs", ".css", ".svg", ".json", ".map")


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


class _ApiHandler(SimpleHTTPRequestHandler):
    """The run endpoint and the JSON answer every API route sends; the page's routes subclass it."""

    #: The page's scripts are `text/javascript` on every host: the host's MIME table may call them `application/javascript`.
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".mjs": "text/javascript"}

    gate: Callable[[BaseHTTPRequestHandler], bool] | None
    routes: ReadRoutes
    writes: WriteRoutes
    streams: Streams
    flows: Collection[str]

    #: Whether the response being written is a hashed build asset's file, which a browser may keep for good.
    _immutable = False

    def send_head(self) -> Any:
        """A static file's headers and the file to copy, gzipped when it is text and the page accepts gzip."""
        path = self.translate_path(self.path)
        self._immutable = urlsplit(self.path).path.startswith(_ASSETS) and os.path.isfile(path)
        if not (path.endswith(_TEXT) and os.path.isfile(path) and accepts_gzip(self.headers.get("Accept-Encoding"))):
            return super().send_head()
        body = _gzipped(path, os.stat(path).st_mtime_ns)
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))  # pragma: no mutate: names are case-insensitive
        self.send_header("Content-Encoding", "gzip")  # pragma: no mutate: names are case-insensitive
        self.send_header("Vary", "Accept-Encoding")  # pragma: no mutate: names are case-insensitive
        self.send_header("Content-Length", str(len(body)))  # pragma: no mutate: names are case-insensitive
        self.end_headers()
        return io.BytesIO(body)

    def end_headers(self) -> None:
        if self._immutable:
            self.send_header("Cache-Control", _KEPT)  # pragma: no mutate: names are case-insensitive
            self._immutable = False
        super().end_headers()

    def handle_one_request(self) -> None:
        """Answer the request; a body its model refuses is a logged 500, since the page reads only what a model names."""
        try:
            super().handle_one_request()
        except ValidationError:
            logger.exception("StarPulse: %s %s built a body its model refuses", self.command, self.path)
            self._send(encode("error", {"error": "the server built a body its contract refuses"}), 500)

    def parse_request(self) -> bool:
        """Parse the request, then let the gate (the test host's write watch) answer or admit it before any route sees it."""
        return super().parse_request() and (self.gate is None or self.gate(self))

    def _send(
        self,
        body: bytes | Encoded,
        status: int = 200,
        cache: str = "no-store",
        content_type: str = "application/json",
        retry_after: int | None = None,
        close: bool = False,
    ) -> None:
        """`body` as JSON unless told otherwise; an `Encoded` one is sent as the gzip it already holds to a page that
        accepts gzip. `retry_after` is the seconds a refused client is asked to wait; `close` ends the connection after
        the answer."""
        if close:
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache)
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        accepted = self.headers.get("Accept-Encoding")
        if isinstance(body, Encoded):
            body, gzipped = body.body, body.gzipped if accepts_gzip(accepted) else None
        else:
            gzipped = compressed(body, accepted)
        if gzipped is not None:
            body = gzipped
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        request = Request(url.path, url.query, self.client_address[0])
        stream = self.streams(request, lambda: self.server.open_stream())  # type: ignore[attr-defined]
        if stream is None:
            self._read(request)
        elif isinstance(stream, Response):
            self._send(*stream)
        else:
            self._stream(stream)

    def do_POST(self) -> None:
        self._answer_write("POST")

    def do_PUT(self) -> None:
        self._answer_write("PUT")

    def do_DELETE(self) -> None:
        self._answer_write("DELETE")

    def _answer_write(self, method: str) -> None:
        """Answer a write through `writes`; a method and path it does not name are a 404."""
        request = WriteRequest(method, urlsplit(self.path).path, self.client_address[0], self.headers, self.rfile.read)
        response = self.writes(request)
        if response is None:
            self.send_error(404)
        else:
            self._send(*response)

    def _read(self, request: Request) -> None:
        """Answer a read route through `routes`, timed as it asks; the page and the static files are not one."""
        with self.routes.watch(request, self.queued_s, self.arrival) as timing:
            response = self.routes(request)
            timing.computed()
            if response is not None:
                self._send(*response)
        if response is None:
            self._page(request.path)

    def _page(self, path: str) -> None:
        if self.writes.post_only(path):
            self.send_response(405)
            self.send_header("Allow", "POST")  # pragma: no mutate: names are case-insensitive
            self.end_headers()
            return
        if path in _PAGES or path.startswith("/flow/") and path[6:] in self.flows - {"board"}:
            self.path = "/index.html"
        super().do_GET()

    def list_directory(self, path: str | os.PathLike[str]) -> None:
        self.send_error(404)

    def _stream(self, stream: Stream) -> None:
        """Hold the connection open and write `stream`'s frames until the page leaves."""
        try:
            self._open_stream()
            for frame in stream.frames:
                self._write_frame(frame)
        except OSError:
            pass
        finally:
            stream.frames.close()
            stream.release()

    def _open_stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")  # pragma: no mutate: names are case-insensitive
        self.send_header("Cache-Control", "no-store")  # pragma: no mutate: names are case-insensitive
        if accepts_gzip(self.headers.get("Accept-Encoding")):
            self.send_header("Content-Encoding", "gzip")  # pragma: no mutate: names are case-insensitive
            self._write_frame = gzip_stream(self.wfile)
        else:
            self._write_frame = self._write_plain
        self.end_headers()

    def _write_plain(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()

    def log_message(self, format: str, *args: Any) -> None:
        pass


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


def request_handler(
    feed: BoardFeed,
    static: Path,
    history: History,
    window: HistoryWindow,
    board: Board,
    services: Services = Services(),
    clock: Callable[[], float] = time.time,
    gate: Callable[[BaseHTTPRequestHandler], bool] | None = None,
) -> type[SimpleHTTPRequestHandler]:

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
    flows = feed.machines.keys()

    class Handler(_ApiHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.gate = gate  # set first: the base __init__ handles the request
            super().__init__(*args, directory=str(static), **kwargs)  # pragma: no mutate: the server passes no kwargs

        def _send(self, body: bytes | Encoded, *args: Any, **kwargs: Any) -> None:
            if self.command != "GET":
                snapshots.require_current()  # a write is answered once the snapshot read after it holds what it published
            super()._send(body, *args, **kwargs)

        def setup(self) -> None:
            super().setup()
            now = time.monotonic()
            arrival = self.server.accepted.pop(self.request, Arrival(now))  # type: ignore[attr-defined]
            self.queued_s = now - arrival.at
            self.arrival = arrival

    Handler.routes, Handler.writes, Handler.streams, Handler.flows = routes, writes, streams, flows
    return Handler
