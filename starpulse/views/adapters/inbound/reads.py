"""The read routes as request-in, response-out handlers: no socket and no web framework, so the ASGI app (and any
other front) calls the same ones."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import parse_qs, unquote

from starpulse.contracts.analytics import Analytics
from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.views.adapters.inbound.compression import Encoded
from starpulse.views.adapters.inbound.routes import (
    _DOCS,
    _LEDGER,
    _MILESTONES,
    _RETIRED,
    _SCHEDULER,
    _SNAPSHOT_BODY,
    _TASK,
    _WINDOW,
)
from starpulse.views.adapters.outbound.process_metrics import process_gauges
from starpulse.views.application.commands.writes import (
    doc_record,
    docs_list,
    history_window,
    milestone_record,
    milestones_list,
    retired_list,
    scheduler,
    task_record,
)
from starpulse.views.application.queries.responses import (
    _error,
    cells_response,
    cited_pulls,
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
from starpulse.views.model.encoding import encode, full_snapshot

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.history_window import HistoryWindow
    from starpulse.board.board_feed import BoardFeed
    from starpulse.board.model.seam import Board
    from starpulse.flow_metrics.adapters.outbound.history import History
    from starpulse.pulls.adapters.outbound.pulls import PullStore
    from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache
    from starpulse.views.ports.services import Services

logger = logging.getLogger(__name__)


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


class Request(NamedTuple):
    """A GET as a server hands it over: the path, the raw query string and the client's address."""

    path: str
    query: str
    client: str


class Response(NamedTuple):
    """What a route answers, in the order a server's `_send` takes it. `retry_after` is the seconds a refused client is
    asked to wait; `close` ends the connection after the answer, since a request body was left unread."""

    body: bytes | Encoded
    status: int = 200
    cache: str = "no-store"
    content_type: str = "application/json"
    retry_after: int | None = None
    close: bool = False


Query = dict[str, list[str]]
Route = Callable[[Request, Query], Response]
Handler = Callable[[Request], Response]


class ReadRoutes:
    """Every read route the page and its scripts call, but for the event streams and the static files. A call answers a
    `Request` with its `Response`, or None where the path is not a read route: a stream, a write the server answers
    405, the page or a file."""

    def __init__(
        self,
        feed: BoardFeed,
        history: History,
        snapshots: SnapshotCache,
        window: HistoryWindow,
        board: Board,
        services: Services,
        clock: Callable[[], float] = time.time,
        page_gauge: Callable[[], str] | None = None,
    ) -> None:
        read, search = board.read, services.search
        self._feed = feed
        self._history = history
        self._snapshots = snapshots
        self._window = window
        self._read = read
        self._search = search
        self._telemetry = services.telemetry
        self._analytics = services.analytics
        self._clock = clock
        self._contract = services.contract
        self._milestones = board
        self._scheduler = services.scheduler
        self._pull_store = services.pulls
        metrics = (
            services.actor_metrics,
            services.lane_metrics,
            services.conformance_metrics,
            services.autopilot_metrics,
            snapshots.metrics,
            page_gauge,
        )
        self._metrics = tuple(m for m in metrics if m)
        self._harnesses = encode("harnesses", (services.harnesses or Harnesses((), {})).as_json())
        self._pull_reads = _PullReads(services.pulls)
        self._slow_reads = _SlowReads(services.slow_read_s)
        flows = feed.machines.keys()
        self._exact: dict[str, Route] = {
            "/api/snapshot": self._snapshot,
            "/api/doctor": self._doctor,
            "/api/machines": lambda request, query: Response(*machines_response(feed, query)),
            "/api/done": lambda request, query: Response(*done_response(feed, read, query)),
            "/api/history": lambda request, query: Response(*history_response(history, query, flows, feed.keys, clock)),
            "/api/pulls": self._pulls,
            "/api/search": lambda request, query: Response(*search_response(search, query)),
            "/metrics": self._prometheus,
            "/api/analytics/health": lambda request, query: Response(
                *health_response(history, query, feed.machines, clock())
            ),
            "/api/analytics/sessions": self._sessions(sessions_response),
            "/api/analytics/steps": self._sessions(steps_response),
            "/api/analytics/transitions": self._titled(transitions_response),
            "/api/analytics/cells": self._titled(cells_response),
            "/api/analytics/graph": self._titled(graph_response),
            "/api/analytics/stages": self._titled(stages_response),
            "/api/analytics/cost-to-go": self._titled(cost_to_go_response),
            "/api/analytics/diff": self._titled(diff_response),
            "/api/analytics/missed-loads": self._ranked(missed_loads_response),
            "/api/analytics/trace-clusters": self._ranked(trace_clusters_response),
            _MILESTONES: self._milestone_list,
            _DOCS: self._doc_list,
            _RETIRED: self._retired,
            "/api/harnesses": lambda request, query: Response(self._harnesses),
            _WINDOW: self._history_window,
            _SCHEDULER: self._scheduler_status,
        }

    @contextmanager
    def watch(self, request: Request, queued_s: float, arrival: Arrival) -> Iterator[Any]:
        """Time the read `request` names when it is one worth timing, `/api/pulls`; any other read is a no-op timer.
        The server holds it open across the send, so the write time counts."""
        if request.path != "/api/pulls":
            yield SimpleNamespace(computed=lambda: None)
            return
        with self._slow_reads.watch(request.query, queued_s, arrival) as timing:
            yield timing

    def routes(self) -> list[tuple[str, Handler]]:
        """Every read route as its path template (`{name}` is a segment, `{name:path}` the rest of the path) and its
        handler, in the order they match. A ledger's stream is `Streams`' and a write is `WriteRoutes`'."""
        records: list[tuple[str, Handler]] = [
            (f"{_SNAPSHOT_BODY}{{key:path}}", self._snapshot_body),
            (f"{_LEDGER}{{rest:path}}", self._ledger),
            (f"{_TASK}{{id:path}}", self._task),
            (f"{_MILESTONES}/{{id:path}}", self._milestone),
            (f"{_DOCS}/{{id:path}}", self._doc),
        ]
        return [*records, *((path, self._queried(route)) for path, route in self._exact.items())]

    def _queried(self, route: Route) -> Handler:
        return lambda request: route(request, parse_qs(request.query))

    def _snapshot_body(self, request: Request) -> Response:
        key = request.path.removeprefix(_SNAPSHOT_BODY)
        body = self._snapshots.body(key)
        if body is None:
            return Response(encode("error", {"error": f"no snapshot {key} is held"}), 404)
        return Response(body, cache="max-age=3600, immutable")

    def _ledger(self, request: Request) -> Response:
        event, _, tail = request.path.removeprefix(_LEDGER).partition("/")
        if tail:
            return Response(_error(f"unknown route {request.path}"), 404)
        return Response(*ledger_response(self._feed, unquote(event), parse_qs(request.query)))

    def _task(self, request: Request) -> Response:
        status, body = task_record(self._feed, self._read, unquote(request.path.removeprefix(_TASK)))
        if status == 200 and (cited := cited_pulls(self._pull_store, body["record"].get("references", []))):
            body["record"]["pulls"] = cited
        return Response(encode("task", body), status)

    def _milestone(self, request: Request) -> Response:
        status, body = milestone_record(self._milestones, unquote(request.path.removeprefix(f"{_MILESTONES}/")))
        return Response(encode("milestone", body), status)

    def _doc(self, request: Request) -> Response:
        status, body = doc_record(self._milestones, unquote(request.path.removeprefix(f"{_DOCS}/")))
        return Response(encode("doc", body), status)

    def _snapshot(self, request: Request, query: Query) -> Response:
        if query.get("view") == ["full"]:
            return Response(encode("snapshot", full_snapshot(self._snapshots.read().snapshot)))
        return Response(self._snapshots.read().encoded)

    def _doctor(self, request: Request, query: Query) -> Response:
        return Response(encode("doctor", self._contract() if self._contract else {"ok": True, "checks": []}))

    def _pulls(self, request: Request, query: Query) -> Response:
        return Response(*self._pull_reads(request.query))

    def _prometheus(self, request: Request, query: Query) -> Response:
        text = "".join(metric() for metric in self._metrics) + process_gauges()
        return Response(text.encode(), content_type="text/plain; version=0.0.4; charset=utf-8")

    def _sessions(self, respond: Callable[..., tuple[bytes, int]]) -> Route:
        return lambda request, query: Response(
            *respond(self._telemetry, query, self._feed.keys, self._clock(), self._analytics)
        )

    def _titled(self, respond: Callable[..., tuple[bytes, int]]) -> Route:
        return lambda request, query: Response(
            *respond(self._telemetry, query, self._feed.keys, self._feed.titled, self._clock(), self._analytics)
        )

    def _ranked(self, respond: Callable[..., tuple[bytes, int]]) -> Route:
        return lambda request, query: Response(
            *respond(
                self._telemetry,
                query,
                self._feed.keys,
                self._feed.titled,
                self._analytics or Analytics(),
                self._clock(),
            )
        )

    def _milestone_list(self, request: Request, query: Query) -> Response:
        status, body = milestones_list(self._milestones)
        return Response(encode("milestones", body), status)

    def _doc_list(self, request: Request, query: Query) -> Response:
        status, body = docs_list(self._milestones)
        return Response(encode("docs", body), status)

    def _retired(self, request: Request, query: Query) -> Response:
        status, body = retired_list(self._milestones, query.get("task", [""])[0], query.get("milestone", [""])[0])
        return Response(encode("retired", body), status)

    def _history_window(self, request: Request, query: Query) -> Response:
        status, body = history_window(request.client, "GET", b"", self._window)
        return Response(encode("window", body), status)

    def _scheduler_status(self, request: Request, query: Query) -> Response:
        status, body = scheduler(request.client, "GET", b"", self._scheduler)
        return Response(encode("scheduler", body), status)
