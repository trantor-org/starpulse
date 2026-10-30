"""Pull requests: the list the page reads and the push that refreshes it.

- `GET /api/pulls`: the pull requests, filtered by the query; a read that takes long is logged.
- `POST /api/pulls/refresh`: the token-guarded push that refreshes the store; 404 where a deployment leaves it
  unconfigured.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import Response

from starpulse.pulls.adapters.inbound.pull_refresh import MAX_BODY as MAX_REFRESH_BODY
from starpulse.views.adapters.inbound.api.answering import answer, reading, seams
from starpulse.views.adapters.inbound.api.neutral import (
    ApiRoute,
    Arrival,
    ReadRoute,
    WriteRequest,
    WriteRoute,
)
from starpulse.views.adapters.inbound.api.neutral import Response as Answer
from starpulse.views.adapters.inbound.api.writing import pushed
from starpulse.views.adapters.inbound.compression import Encoded
from starpulse.views.application.queries.responses import pulls_response

if TYPE_CHECKING:  # annotation only
    from starpulse.pulls.adapters.outbound.pulls import PullStore
    from starpulse.views.adapters.inbound.api.routing import Api


class PullReads:
    """`/api/pulls`' answers, by query, held until the store saves: the unfiltered list is ~1 MB to read, encode and
    gzip, and every page asks for it. A save builds the unfiltered answer itself, in the poller's thread, so a reader
    finds it held; readers asking together for any other answer share one computation, since each extra one only
    waits behind the rest for the GIL. A read of one pull request (`repo` and `number`) is a lookup of microseconds:
    it takes neither the computation lock, which a rebuild of the list holds for seconds, nor a held slot."""

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
        asked = parse_qs(query)
        if "repo" in asked and "number" in asked:
            body, status = pulls_response(self._pulls, asked)
            return Encoded.of(body), status
        held = self._current(query)
        if held is None:
            with self._computing:
                held = self._current(query)
                if held is None:
                    rev = self._pulls.rev if self._pulls else 0
                    body, status = pulls_response(self._pulls, asked)
                    held = (rev, Encoded.of(body), status)
                    with self._lock:
                        self._held[query] = held
                        while len(self._held) > self.KEEP:
                            self._held.popitem(last=False)
        return held[1], held[2]


@reading
def pulls(request: Request) -> Response:
    return answer(request, *seams(request).pull_reads(request.url.query))


def timed(request: Request, arrival: Arrival) -> AbstractContextManager[Any]:
    return seams(request).slow_reads.watch(request.url.query, arrival)


def routes(api: Api) -> list[ApiRoute]:
    refresh = api.services.pull_refresh

    def push(request: WriteRequest) -> Answer | None:
        return None if refresh is None else pushed(request, "ingest", refresh, MAX_REFRESH_BODY)

    return [ReadRoute("/pulls", pulls, timed), WriteRoute("/pulls/refresh", ("POST",), push)]
