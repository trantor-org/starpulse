"""The request handler: the page and its assets, the event streams and every `/api` route."""

from __future__ import annotations

import functools
import gzip
import hashlib
import io
import logging
import os
import queue
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError

from starpulse._internal.board.seam import (
    AssigneeWriter,
    Board,
    MoveWriter,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskRestorer,
    Written,
)
from starpulse._internal.runs.ingest import MAX_BODY, MAX_FORWARD_BODY, ForwardIngest, Ingest
from starpulse._internal.pulls.pull_refresh import MAX_BODY as MAX_REFRESH_BODY
from starpulse._internal.pulls.pull_refresh import PullRefresh
from starpulse._internal.server.compression import LEVEL, Encoded, accepts_gzip, compressed, gzip_stream
from starpulse._internal.server.process_metrics import process_gauges
from starpulse._internal.hub.forward import Forwarder
from starpulse._internal.server.column_stream import ColumnViews, Interest
from starpulse._internal.server.snapshot_cache import SnapshotCache
from starpulse._internal.server.writes import (
    autopilot,
    OPERATOR,
    archive_doc,
    archive_milestone,
    archive_task,
    claim_task,
    complete_task,
    create_doc,
    create_milestone,
    create_task,
    doc_record,
    import_retired,
    record_miss,
    record_verdict,
    docs_list,
    edit_doc,
    edit_milestone,
    edit_task,
    forwarding,
    history_window,
    milestone_record,
    milestones_list,
    move_task,
    park_task,
    rerun_dag,
    restore_doc,
    restore_task,
    retire_task,
    retired_list,
    review_task,
    run_dag,
    start_task,
    task_record,
    write_refusal,
)
from starpulse._internal.server.responses import (
    _error,
    cells_response,
    cost_to_go_response,
    diff_response,
    done_response,
    graph_response,
    health_response,
    history_response,
    ledger_response,
    machines_response,
    missed_loads_response,
    pulls_response,
    search_response,
    sessions_response,
    stages_response,
    steps_response,
    trace_clusters_response,
    transitions_response,
)
from starpulse._internal.server.routes import (
    _ARCHIVE,
    _AUTOPILOT,
    _CLAIM,
    _COMPLETE,
    _DOCS,
    _DOC_ARCHIVE,
    _DOC_EDIT,
    _DOC_RESTORE,
    _DOC_WRITES,
    _EDIT,
    _FORWARD,
    _FORWARDING,
    _HELD,
    _INGEST,
    _INSIGHTS,
    _LANES,
    _LEDGER,
    _MILESTONES,
    _MILESTONE_ARCHIVE,
    _MISS,
    _MILESTONE_EDIT,
    _MILESTONE_WRITES,
    _MOVE,
    _PAGES,
    _PARK,
    _PULL_REFRESH,
    _RERUN,
    _RERUN_TAIL,
    _RESTORE,
    _RETIRE,
    _RETIRED,
    _RETIRED_IMPORT,
    _REVIEW,
    _RETIRED_WRITES,
    _RUN,
    _SNAPSHOT_BODY,
    _START,
    _TASK,
    _TASKS,
    _TASK_WRITES,
    _VERDICT,
    _WINDOW,
    _WRITES,
    _is_rerun,
)
from starpulse._internal.server.encoding import encode, event, full_snapshot
from starpulse._internal.config.level import Level
from starpulse._internal.config.config import SLOW_READ_S
from starpulse._internal.config.harnesses import Harnesses
from starpulse._internal.feed.history_window import HistoryWindow
from starpulse._internal.config.analytics import Analytics
from starpulse._internal.harnesses.telemetry import TelemetryLog

if TYPE_CHECKING:  # annotation only: a runtime import would put the autopilot in the Delivery worker's import closure
    from starpulse._internal.autopilot.remote import Remote
    from starpulse._internal.autopilot.runtime import Runtime
    from starpulse._internal.eventlog.history import History
    from starpulse._internal.feed.board_feed import BoardFeed
    from starpulse._internal.feed.search import SearchIndex
    from starpulse._internal.level.insights import Insights
    from starpulse._internal.pulls.pulls import PullStore


logger = logging.getLogger(__name__)


#: Seconds a stream refused for a full stream pool is asked to wait before it reconnects.
_STREAM_RETRY_S = 5


class _PullReads:
    """`/api/pulls`' answers, by query, held until the store saves: the unfiltered list is ~1 MB to read, encode and
    gzip, and every page asks for it. A save builds the unfiltered answer itself, in the poller's thread, so a reader
    finds it held; readers asking together for any other answer share one computation, since each extra one only
    waits behind the rest for the GIL."""

    #: How many distinct queries are held; past it the oldest is dropped.
    KEEP = 16

    def __init__(self, pulls: PullStore | None) -> None:
        self._pulls = pulls
        self._held: OrderedDict[str, tuple[int, Encoded, int]] = OrderedDict()
        self._lock = threading.Lock()
        self._computing = threading.Lock()
        if pulls:
            pulls.subscribe(lambda: self(""))

    def _current(self, query: str) -> tuple[int, Encoded, int] | None:
        rev = self._pulls.rev if self._pulls else 0
        with self._lock:
            held = self._held.get(query)
        return held if held and held[0] == rev else None

    def __call__(self, query: str) -> tuple[Encoded, int]:
        held = self._current(query)
        if held is None:
            with self._computing:
                held = self._current(query)
                if held is None:
                    rev = self._pulls.rev if self._pulls else 0
                    body, status = pulls_response(self._pulls, parse_qs(query))
                    held = (rev, Encoded.of(body), status)
                    with self._lock:
                        self._held[query] = held
                        while len(self._held) > self.KEEP:
                            self._held.popitem(last=False)
        return held[1], held[2]


class _SlowReads:
    """Logs each `/api/pulls` read that took `threshold_s` seconds or more from accept to the last byte written, with
    the seconds it waited for a handler thread, computed its answer and wrote it, the reads in flight when it began, and
    the request workers busy and streams open when it was accepted, so a stall of the whole process can be told apart by
    the phase, and the occupant of the pool, that held the time."""

    class _Read:
        def __init__(self, started: float) -> None:
            self.started = started
            self.computed_at: float | None = None

        def computed(self) -> None:
            self.computed_at = time.monotonic()

    def __init__(self, threshold_s: float) -> None:
        self._threshold_s = threshold_s
        self._lock = threading.Lock()
        self._in_flight = 0

    @contextmanager
    def watch(self, query: str, queued_s: float, arrival: Arrival) -> Iterator[_Read]:
        with self._lock:
            self._in_flight += 1
            in_flight = self._in_flight
        read = self._Read(time.monotonic())
        try:
            yield read
        finally:  # a write that fails on a closed socket is the slow read most worth the line
            ended = time.monotonic()
            with self._lock:
                self._in_flight -= 1
            computed_at = read.computed_at if read.computed_at is not None else ended
            compute_s, write_s = computed_at - read.started, ended - computed_at
            if queued_s + compute_s + write_s >= self._threshold_s:
                logger.warning(
                    "slow_read route=/api/pulls query=%s queue_s=%.3f compute_s=%.3f write_s=%.3f in_flight=%d"
                    " busy=%d streams=%d",
                    query,
                    queued_s,
                    compute_s,
                    write_s,
                    in_flight,
                    arrival.busy,
                    arrival.streams,
                )


class Arrival(NamedTuple):
    """A connection when it was accepted: the time, the request workers busy or about to be (itself included) and the
    streams open."""

    at: float
    busy: int = 0
    streams: int = 0


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

    starts: Mapping[str, Callable[[str], str]]
    reruns: Mapping[str, Callable[[str, Mapping[str, str]], str]]
    run_safe: Collection[str]
    feed: BoardFeed
    window: HistoryWindow
    writer: MoveWriter
    assign: AssigneeWriter
    start_session: Callable[..., str] | None
    harnesses: Harnesses | None
    read: TaskReader | None
    edit: TaskEditor | None
    archive: TaskArchiver | None
    restore: TaskRestorer | None
    complete: TaskCompleter | None
    create: TaskCreator | None
    ingest: Ingest | None
    insights: Insights | None
    gate: Callable[[BaseHTTPRequestHandler], bool] | None
    forward: ForwardIngest | None
    pull_refresh: PullRefresh | None
    forwarding: Forwarder | None
    autopilot: Runtime | Remote | None
    milestones: Board | None

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
        """Parse the request, then let the gate (a hub's sign-in) answer or admit it before any route sees it."""
        return super().parse_request() and (self.gate is None or self.gate(self))

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if (
            path.startswith(_RUN)
            or _is_rerun(path)
            or path
            in {
                _MOVE,
                _START,
                _EDIT,
                _ARCHIVE,
                _VERDICT,
                _MISS,
                _RESTORE,
                _COMPLETE,
                _CLAIM,
                _PARK,
                _REVIEW,
                _TASKS,
                _INGEST,
                _FORWARD,
                _INSIGHTS,
                _PULL_REFRESH,
                *_MILESTONE_WRITES,
                *_DOC_WRITES,
                *_RETIRED_WRITES,
            }
        ):
            self.send_response(405)
            self.send_header("Allow", "POST")  # pragma: no mutate: names are case-insensitive
            self.end_headers()
        else:
            super().do_GET()

    def _refused_write(self) -> bool:
        """Answer a write another web page may have sent with its refusal; whether it did."""
        headers = self.headers
        if (refusal := write_refusal(headers.get("Origin"), headers.get("Host"), headers.get("Content-Type"))) is None:
            return False
        self._send(encode("error", refusal[1]), refusal[0])
        return True

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if (path in _TASK_WRITES or path.startswith(_RUN) or _is_rerun(path)) and self._refused_write():
            return
        kind = _WRITES.get(path, "run")
        if path in _TASK_WRITES:
            declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
            raw = self.rfile.read(int(declared or 0))
            if path == _MOVE:
                status, body = move_task(self.client_address[0], raw, self.feed, self.writer)
            elif path == _EDIT:
                status, body = edit_task(self.client_address[0], raw, self.feed, self.read, self.edit)
            elif path == _ARCHIVE:
                status, body = archive_task(self.client_address[0], raw, self.feed, self.archive)
            elif path == _VERDICT:
                status, body = record_verdict(self.client_address[0], raw, self.feed, self.read, self.edit)
            elif path == _MISS:
                status, body = record_miss(
                    self.client_address[0], raw, self.feed, self.read, self.edit, self.archive, self.create
                )
            elif path == _RESTORE:
                status, body = restore_task(self.client_address[0], raw, self.restore)
            elif path == _RETIRE:
                status, body = retire_task(self.client_address[0], raw, self.milestones)
            elif path == _RETIRED_IMPORT:
                status, body = import_retired(self.client_address[0], raw, self.milestones)
            elif path == _CLAIM:
                status, body = claim_task(self.client_address[0], raw, self.feed, self.writer)
            elif path == _PARK:
                status, body = park_task(self.client_address[0], raw, self.feed, self.read, self.edit)
            elif path == _REVIEW:
                status, body = review_task(self.client_address[0], raw, self.feed, self.read, self.edit)
            elif path == _COMPLETE:
                status, body = complete_task(self.client_address[0], raw, self.feed, self.complete)
            elif path == _TASKS:
                status, body = create_task(self.client_address[0], raw, self.create, self.feed)
            elif path == _MILESTONES:
                status, body = create_milestone(self.client_address[0], raw, self.milestones)
            elif path == _MILESTONE_EDIT:
                status, body = edit_milestone(self.client_address[0], raw, self.milestones)
            elif path == _MILESTONE_ARCHIVE:
                status, body = archive_milestone(self.client_address[0], raw, self.milestones)
            elif path == _DOCS:
                status, body = create_doc(self.client_address[0], raw, self.milestones)
            elif path == _DOC_EDIT:
                status, body = edit_doc(self.client_address[0], raw, self.milestones)
            elif path == _DOC_ARCHIVE:
                status, body = archive_doc(self.client_address[0], raw, self.milestones)
            elif path == _DOC_RESTORE:
                status, body = restore_doc(self.client_address[0], raw, self.milestones)
            else:
                status, body = start_task(
                    self.client_address[0], raw, self.feed, self.assign, self.start_session, self.harnesses
                )
        elif path == _INGEST and self.ingest is not None:
            status, body = self._pushed(self.ingest, MAX_BODY)
        elif path == _FORWARD and self.forward is not None:
            status, body = self._pushed(self.forward, MAX_FORWARD_BODY)
        elif path == _INSIGHTS and self.insights is not None:
            status, body = self._pushed(self.insights, MAX_BODY)
        elif path == _PULL_REFRESH and self.pull_refresh is not None:
            status, body = self._pushed(self.pull_refresh, MAX_REFRESH_BODY)
        elif _is_rerun(path):
            name = unquote(path.removeprefix(_RERUN).removesuffix(_RERUN_TAIL))
            status, body = rerun_dag(self.client_address[0], name, self.feed, self.reruns, self.run_safe)
        elif path.startswith(_RUN):
            status, body = run_dag(self.client_address[0], unquote(path.removeprefix(_RUN)), self.starts, self.run_safe)
        else:
            self.send_error(404)
            return
        self._send(encode(kind, body), status)

    def _pushed(self, ingest: Callable[[str | None, bytes], tuple[int, dict]], limit: int) -> tuple[int, dict]:
        """Answer one token-guarded push; a body over `limit` is refused unread and the connection closed."""
        try:
            declared = int(self.headers.get("Content-Length") or 0)  # pragma: no mutate: case-insensitive
        except ValueError:
            declared = 0
        if declared > limit:
            self.close_connection = True  # the body was not read, so the connection cannot carry another request
            return 413, {"error": f"a body is at most {limit} bytes"}
        return ingest(self.headers.get("Authorization"), self.rfile.read(max(declared, 0)))

    def do_PUT(self) -> None:
        self._window("PUT")

    def do_DELETE(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith(f"{_INSIGHTS}/") and self.insights is not None:
            status, body = self.insights.retract(unquote(path.removeprefix(f"{_INSIGHTS}/")))
            self._send(encode("insight", body), status)
        else:
            self._window("DELETE")

    def _window(self, method: str) -> None:
        """Answer the route a PUT or DELETE names: the history window's, or a PUT to the forwarding opt-in or the autopilot switch."""
        path = urlsplit(self.path).path
        if path == _AUTOPILOT and method == "PUT":
            if self._refused_write():
                return
            declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
            self._send(*self._autopilot(method, self.rfile.read(int(declared or 0))))
            return
        if path == _FORWARDING and method == "PUT":
            if self._refused_write():
                return
            declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
            self._send(*self._forwarding(method, self.rfile.read(int(declared or 0))))
            return
        if path != _WINDOW:
            self.send_error(404)
            return
        if method != "GET" and self._refused_write():
            return
        declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
        status, body = history_window(self.client_address[0], method, self.rfile.read(int(declared or 0)), self.window)
        self._send(encode("window", body), status)

    def _autopilot(self, method: str, raw: bytes) -> tuple[bytes, int]:
        status, body = autopilot(self.client_address[0], method, raw, self.autopilot)
        return encode("autopilot", body), status

    def _forwarding(self, method: str, raw: bytes) -> tuple[bytes, int]:
        status, body = forwarding(self.client_address[0], method, raw, self.forwarding)
        return encode("forwarding", body), status

    def _send(
        self,
        body: bytes | Encoded,
        status: int = 200,
        cache: str = "no-store",
        content_type: str = "application/json",
        retry_after: int | None = None,
    ) -> None:
        """`body` as JSON unless told otherwise; an `Encoded` one is sent as the gzip it already holds to a page that
        accepts gzip. `retry_after` is the seconds a refused client is asked to wait."""
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


def _no_writer(task: str, status: str, actor: str = OPERATOR) -> Written:
    return Written(False, "no board writer is configured", unavailable=True)


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
    starts: Mapping[str, Callable[[str], str]],
    run_safe: Collection[str],
    history: History,
    window: HistoryWindow,
    writer: MoveWriter = _no_writer,
    harnesses: Harnesses | None = None,
    assign: AssigneeWriter = _no_writer,
    start_session: Callable[..., str] | None = None,
    read: TaskReader | None = None,
    edit: TaskEditor | None = None,
    archive: TaskArchiver | None = None,
    create: TaskCreator | None = None,
    clock: Callable[[], float] = time.time,
    ingest: Ingest | None = None,
    gate: Callable[[BaseHTTPRequestHandler], bool] | None = None,
    forward: ForwardIngest | None = None,
    level: Level | None = None,
    insights: Insights | None = None,
    forwarding: Forwarder | None = None,
    autopilot: Runtime | Remote | None = None,
    reruns: Mapping[str, Callable[[str, Mapping[str, str]], str]] | None = None,
    contract: Callable[[], dict[str, Any]] | None = None,
    milestones: Board | None = None,
    pulls: PullStore | None = None,
    telemetry: TelemetryLog | None = None,
    complete: TaskCompleter | None = None,
    restore: TaskRestorer | None = None,
    search: SearchIndex | None = None,
    analytics: Analytics | None = None,
    pull_refresh: PullRefresh | None = None,
    slow_read_s: float = SLOW_READ_S,
    actor_metrics: Callable[[], str] | None = None,
    lane_metrics: Callable[[], str] | None = None,
    conformance_metrics: Callable[[], str] | None = None,
) -> type[SimpleHTTPRequestHandler]:
    from starpulse._internal.server import (
        server as views,
    )  # late: `server` imports this module and keeps the views and stream timings its tests patch

    configured = harnesses or Harnesses((), {})
    harnesses_body = encode("harnesses", configured.as_json())
    snapshots = SnapshotCache(feed)
    column_views = ColumnViews()
    pull_reads = _PullReads(pulls)
    slow_reads = _SlowReads(slow_read_s)
    event_text = views.EventText()
    flows = feed.machines.keys()

    class Handler(_ApiHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.starts = starts  # set first: the base __init__ handles the request
            self.reruns = reruns or {}
            self.run_safe = run_safe
            self.feed = feed
            self.window = window
            self.writer = writer
            self.assign = assign
            self.start_session = start_session
            self.harnesses = configured
            self.read = read
            self.edit = edit
            self.archive = archive
            self.restore = restore
            self.complete = complete
            self.create = create
            self.ingest = ingest
            self.insights = insights
            self.gate = gate
            self.forward = forward
            self.pull_refresh = pull_refresh
            self.forwarding = forwarding
            self.autopilot = autopilot
            self.milestones = milestones
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

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/api/events":
                self._stream_events(parse_qs(url.query).get("snapshot") == ["ref"])
            elif url.path == _HELD:
                query = parse_qs(url.query)
                self._stream_held((query.get("assignee") or query.get("holder") or [""])[0])  # legacy `holder`
            elif url.path == _LANES:
                self._stream_columns("lanes", None, parse_qs(url.query).get("state", []))
            elif url.path.startswith(_SNAPSHOT_BODY):
                self._snapshot_body(url.path.removeprefix(_SNAPSHOT_BODY))
            elif url.path == "/api/snapshot":
                if parse_qs(url.query).get("view") == ["full"]:
                    self._send(encode("snapshot", full_snapshot(snapshots.read().snapshot)))
                else:
                    self._send(snapshots.read().encoded)
            elif url.path.startswith(_LEDGER):
                event, _, tail = url.path.removeprefix(_LEDGER).partition("/")
                if tail == "events":
                    self._stream_ledger(unquote(event))
                elif tail:
                    self._send(_error(f"unknown route {url.path}"), 404)
                else:
                    self._send(*ledger_response(feed, unquote(event), parse_qs(url.query)))
            elif url.path == "/api/doctor":
                self._send(encode("doctor", contract() if contract else {"ok": True, "checks": []}))
            elif url.path == "/api/machines":
                self._send(*machines_response(feed, parse_qs(url.query)))
            elif url.path == "/api/done":
                self._send(*done_response(feed, read, parse_qs(url.query)))
            elif url.path == "/api/history":
                self._send(*history_response(history, parse_qs(url.query), flows, feed.keys))
            elif url.path == "/api/pulls":
                with slow_reads.watch(url.query, self.queued_s, self.arrival) as timing:
                    body, status = pull_reads(url.query)
                    timing.computed()
                    self._send(body, status)
            elif url.path == "/api/search":
                self._send(*search_response(search, parse_qs(url.query)))
            elif url.path == "/metrics":
                self._send(
                    (
                        (actor_metrics() if actor_metrics else "")
                        + (lane_metrics() if lane_metrics else "")
                        + (conformance_metrics() if conformance_metrics else "")
                        + build_gauge(static)
                        + process_gauges()
                    ).encode(),
                    content_type="text/plain; version=0.0.4; charset=utf-8",
                )
            elif url.path == "/api/analytics/health":
                self._send(*health_response(history, parse_qs(url.query), feed.machines, clock()))
            elif url.path == "/api/analytics/sessions":
                self._send(*sessions_response(telemetry, parse_qs(url.query), feed.keys, clock(), analytics))
            elif url.path == "/api/analytics/steps":
                self._send(*steps_response(telemetry, parse_qs(url.query), feed.keys, clock(), analytics))
            elif url.path == "/api/analytics/transitions":
                self._send(
                    *transitions_response(telemetry, parse_qs(url.query), feed.keys, feed.titled, clock(), analytics)
                )
            elif url.path == "/api/analytics/cells":
                self._send(*cells_response(telemetry, parse_qs(url.query), feed.keys, feed.titled, clock(), analytics))
            elif url.path == "/api/analytics/graph":
                self._send(*graph_response(telemetry, parse_qs(url.query), feed.keys, feed.titled, clock(), analytics))
            elif url.path == "/api/analytics/stages":
                self._send(*stages_response(telemetry, parse_qs(url.query), feed.keys, feed.titled, clock(), analytics))
            elif url.path == "/api/analytics/cost-to-go":
                self._send(
                    *cost_to_go_response(telemetry, parse_qs(url.query), feed.keys, feed.titled, clock(), analytics)
                )
            elif url.path == "/api/analytics/diff":
                self._send(*diff_response(telemetry, parse_qs(url.query), feed.keys, feed.titled, clock(), analytics))
            elif url.path == "/api/analytics/missed-loads":
                self._send(
                    *missed_loads_response(
                        telemetry, parse_qs(url.query), feed.keys, feed.titled, analytics or Analytics(), clock()
                    )
                )
            elif url.path == "/api/analytics/trace-clusters":
                self._send(
                    *trace_clusters_response(
                        telemetry, parse_qs(url.query), feed.keys, feed.titled, analytics or Analytics(), clock()
                    )
                )
            elif url.path == "/api/level":
                self._send(*views.level_response(history, parse_qs(url.query), level, feed.machines, clock()))
            elif url.path == "/api/level/trajectories":
                self._send(*views.trajectories_response(history, parse_qs(url.query), level, feed.machines, clock()))
            elif url.path == "/api/level/what-if":
                self._send(*views.what_if_response(history, parse_qs(url.query), level, feed.machines, clock()))
            elif url.path.startswith(_TASK):
                status, body = task_record(feed, read, unquote(url.path.removeprefix(_TASK)))
                self._send(encode("task", body), status)
            elif url.path == _MILESTONES:
                status, body = milestones_list(self.milestones)
                self._send(encode("milestones", body), status)
            elif url.path.startswith(f"{_MILESTONES}/") and url.path not in _MILESTONE_WRITES:
                status, body = milestone_record(self.milestones, unquote(url.path.removeprefix(f"{_MILESTONES}/")))
                self._send(encode("milestone", body), status)
            elif url.path == _DOCS:
                status, body = docs_list(self.milestones)
                self._send(encode("docs", body), status)
            elif url.path.startswith(f"{_DOCS}/") and url.path not in _DOC_WRITES:
                status, body = doc_record(self.milestones, unquote(url.path.removeprefix(f"{_DOCS}/")))
                self._send(encode("doc", body), status)
            elif url.path == _RETIRED:
                status, body = retired_list(self.milestones, parse_qs(url.query).get("task", [""])[0])
                self._send(encode("retired", body), status)
            elif url.path == "/api/harnesses":
                self._send(harnesses_body)
            elif url.path == _WINDOW:
                self._window("GET")  # pragma: no mutate: any method but PUT and DELETE reads the window
            elif url.path == _FORWARDING:
                self._send(*self._forwarding("GET", b""))
            elif url.path == _AUTOPILOT:
                self._send(*self._autopilot("GET", b""))
            elif url.path in _PAGES or url.path.startswith("/flow/") and url.path[6:] in flows - {"board"}:
                self.path = "/index.html"
                super().do_GET()
            else:
                super().do_GET()

        def list_directory(self, path: str | os.PathLike[str]) -> None:
            self.send_error(404)

        def _snapshot_body(self, key: str) -> None:
            body = snapshots.body(key)
            if body is None:
                return self._send(encode("error", {"error": f"no snapshot {key} is held"}), 404)
            self._send(body, cache="max-age=3600, immutable")

        def _stream_events(self, by_ref: bool = False) -> None:
            """Hold the connection open: the Board's snapshot, then each change as it happens. `by_ref` sends the snapshot
            as `ref <path>`, the path its body is read from: a browser reads a long event on its main thread, a fetched
            body off it."""
            if not self._admit_stream():
                return
            changes = None
            try:
                # The held snapshot is sent as it is, however many changes it lacks, so a page connecting while the next
                # one is built is not held up by it: it applies those changes after it.
                served = snapshots.latest() or snapshots.get()
                while (attached := feed.watch_from(served.sent)) is None:
                    served = snapshots.get()
                missed, changes = attached
                self._open_stream()
                self._frame("snapshot", f"ref {_SNAPSHOT_BODY}{served.key}" if by_ref else served.body.decode())
                if (build := page_build(static)) is not None:
                    self._frame(
                        "build", _build_text(build)
                    )  # a page holding another build than this one is out of date
                for change in missed:
                    self._event(*change)
                while True:
                    try:
                        change = changes.get(timeout=views._PING_S)
                    except queue.Empty:
                        self._write(b": ping\n\n")  # a closed page fails this write, which ends the stream
                        continue
                    try:
                        self._event(*change)
                    finally:
                        changes.task_done()  # `feed.announce` waits for the marks of what it queued
            except OSError:
                pass
            except ValidationError:
                logger.exception("StarPulse: /api/events sent a body its model refuses; the stream ends")
            finally:
                if changes is not None:
                    feed.unsubscribe(changes)

        def _admit_stream(self) -> bool:
            """Move this connection's worker into the stream pool, or answer 503 when that pool is full."""
            if self.server.open_stream():  # type: ignore[attr-defined]
                return True
            self._send(_error("too many open streams; retry shortly"), 503, retry_after=_STREAM_RETRY_S)
            return False

        def _open_stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")  # pragma: no mutate: names are case-insensitive
            self.send_header("Cache-Control", "no-store")  # pragma: no mutate: names are case-insensitive
            if accepts_gzip(self.headers.get("Accept-Encoding")):
                self.send_header("Content-Encoding", "gzip")  # pragma: no mutate: names are case-insensitive
                self._write = gzip_stream(self.wfile)
            else:
                self._write = self._write_plain
            self.end_headers()

        def _stream_ledger(self, event: str) -> None:
            """Hold the connection open: `event`'s newest rows as a `page` event (`{rows, more}`), then a `rows` event (`{rows}`) each
            time rows of that Ledger change. A page reads this while it has the Ledger open; the main stream carries
            no row."""
            if not self._admit_stream():
                return
            changes = None
            try:
                if (watched := feed.watch_ledger(event)) is None:
                    return self._send(_error(f"no ledger for {event}"), 404)
                rows, more, changes = watched
                self._open_stream()
                self._frame("page", encode("ledger", {"rows": rows, "more": more}).decode())
                while True:
                    try:
                        self._frame("rows", encode("ledger_rows", changes.get(timeout=views._PING_S)).decode())
                    except queue.Empty:
                        self._write(b": ping\n\n")  # a closed page fails this write, which ends the stream
            except OSError:
                pass
            finally:
                if changes is not None:
                    feed.unwatch_ledger(changes)

        def _stream_held(self, assignee: str) -> None:
            """Hold the connection open: the tasks `assignee` holds, then those tasks again each time they change, so a
            session's band redraws on a change instead of asking."""
            if not assignee:
                return self._send(_error(f"name the session: {_HELD}?assignee=<session>"), 400)
            self._stream_columns("held", assignee)

        def _stream_columns(self, event: str, assignee: str | None, states: Sequence[str] = ()) -> None:
            """Hold the connection open: the Board's columns (only `states`, when named) with the tasks `assignee` holds
            (all, when None), as `event`, then again each time a change alters that view. A burst of changes settles
            before one reread, and the streams that reread for a change read one build of the columns."""
            if not self._admit_stream():
                return
            changes = None
            try:
                served = snapshots.after_current()
                while (attached := feed.watch_from(served.sent)) is None:
                    served = snapshots.after_current()
                missed, changes = attached
                if missed:
                    served = (
                        snapshots.after_current()
                    )  # the view must include what was published after the snapshot it started from
                self._open_stream()
                sent = None
                while True:
                    view, text = column_views.render(served, assignee, states)
                    if view != sent:
                        self._frame(event, text)
                        sent = view
                        interest = Interest(view, assignee, states)
                    self._wait_touched(changes, interest)
                    time.sleep(views._HELD_SETTLE_S)
                    while not changes.empty():
                        changes.get_nowait()
                        changes.task_done()
                    served = snapshots.after_current()
            except OSError:
                pass
            finally:
                if changes is not None:
                    feed.unsubscribe(changes)

        def _wait_touched(self, changes: queue.Queue, interest: Interest) -> None:
            """Take changes off `changes` until one alters the view `interest` describes, pinging while none arrives."""
            while True:
                try:
                    change = changes.get(timeout=views._PING_S)
                except queue.Empty:
                    self._write(b": ping\n\n")  # a closed session fails this write, which ends the stream
                    continue
                changes.task_done()  # `feed.announce` waits for the marks of what it queued
                if interest.touched_by(*change):
                    return

        def _event(self, name: str, data: dict) -> None:
            self._frame(name, event_text(name, data))

        def _frame(self, name: str, data: str) -> None:
            self._write(f"event: {name}\ndata: {data}\n\n".encode())

        def _write_plain(self, data: bytes) -> None:
            self.wfile.write(data)
            self.wfile.flush()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler
