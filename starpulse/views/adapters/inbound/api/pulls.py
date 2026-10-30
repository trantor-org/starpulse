"""Pull requests: the list the page reads and the push that refreshes it.

- `GET /api/pulls`: the pull requests, filtered by the query; a read that takes long is logged.
- `POST /api/pulls/refresh`: the token-guarded push that refreshes the store; 404 where a deployment leaves it
  unconfigured.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from starpulse.pulls.adapters.inbound.pull_refresh import MAX_BODY as MAX_REFRESH_BODY
from starpulse.views.adapters.inbound.api.neutral import (
    ApiRoute,
    Arrival,
    ReadRoute,
    Request,
    Response,
    WriteRequest,
    WriteRoute,
)
from starpulse.views.adapters.inbound.api.writing import pushed
from starpulse.views.adapters.inbound.compression import Encoded
from starpulse.views.application.queries.responses import pulls_response

if TYPE_CHECKING:  # annotation only
    from starpulse.pulls.adapters.outbound.pulls import PullStore
    from starpulse.views.adapters.inbound.api.routing import Api

logger = logging.getLogger(__name__)


class PullReads:
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


class SlowReads:
    """Logs each `/api/pulls` read that took `threshold_s` seconds or more from accept to the last byte written, with
    the seconds it waited for a handler thread, computed its answer and wrote it, the reads in flight when it began, and
    the request workers busy and streams open when it was accepted, so a stall of the whole process can be told apart by
    the phase, and the occupant of the pool, that held the time."""

    class _Read:
        def __init__(self) -> None:
            self.ran_at: float | None = None
            self.computed_at: float | None = None

        def ran(self) -> None:
            self.ran_at = time.monotonic()

        def computed(self) -> None:
            self.computed_at = time.monotonic()

    def __init__(self, threshold_s: float) -> None:
        self._threshold_s = threshold_s
        self._lock = threading.Lock()
        self._in_flight = 0

    @contextmanager
    def watch(self, query: str, arrival: Arrival) -> Iterator[_Read]:
        with self._lock:
            self._in_flight += 1
            in_flight = self._in_flight
        read = self._Read()
        try:
            yield read
        finally:  # a write that fails on a closed socket is the slow read most worth the line
            ended = time.monotonic()
            with self._lock:
                self._in_flight -= 1
            ran_at = read.ran_at if read.ran_at is not None else ended
            computed_at = read.computed_at if read.computed_at is not None else ended
            queued_s, compute_s, write_s = ran_at - arrival.at, computed_at - ran_at, ended - computed_at
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


def routes(api: Api) -> list[ApiRoute]:
    services = api.services
    held = PullReads(services.pulls)
    slow = SlowReads(services.slow_read_s)
    refresh = services.pull_refresh

    def pulls(request: Request) -> Response:
        return Response(*held(request.query))

    def timed(request: Request, arrival: Arrival) -> AbstractContextManager[Any]:
        return slow.watch(request.query, arrival)

    def push(request: WriteRequest) -> Response | None:
        return None if refresh is None else pushed(request, "ingest", refresh, MAX_REFRESH_BODY)

    return [ReadRoute("/pulls", pulls, timed), WriteRoute("/pulls/refresh", ("POST",), push)]
