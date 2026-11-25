"""What the page asks of the Board and its deployment besides the snapshot.

- `GET /api/doctor`: the contract report.
- `GET /api/health`: 200 when the server can serve the board, 503 naming each component that is not ready.
- `GET /api/done`, `/api/search`: the Done lane and a search of the tasks.
- `GET /api/search/similar`: `/api/search` that waits to embed a new query, for a caller that needs the tasks nearest
  in meaning, not an answer within a budget. A search that takes long is logged with its `embed_s` and `sql_s`.
- `GET /api/harnesses`: the harnesses a session may start on.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.views.adapters.inbound.api.answering import SPANS, answer, query, reading, seams
from starpulse.views.adapters.inbound.api.slow_reads import SlowReads
from starpulse.views.adapters.inbound.api.table import ApiRoute, Arrival, ReadRoute
from starpulse.views.application.queries.responses import done_response, search_response
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def doctor(request: Request) -> Response:
    contract = seams(request).services.contract
    return answer(request, encode("doctor", contract() if contract else {"ok": True, "checks": []}))


@reading
def ready(request: Request) -> Response:
    report = seams(request).services.ready
    body = report() if report else {"ready": True, "components": {}}
    return answer(request, encode("ready", body), 200 if body["ready"] else 503)


@reading
def done(request: Request) -> Response:
    api = seams(request)
    return answer(request, *done_response(api.feed, api.board.read, query(request)))


def _spans(request: Request) -> dict[str, float] | None:
    return request.scope.get(SPANS)


@reading
def search(request: Request) -> Response:
    return answer(request, *search_response(seams(request).services.search, query(request), spans=_spans(request)))


@reading
def similar(request: Request) -> Response:
    found = search_response(seams(request).services.search, query(request), wait=True, spans=_spans(request))
    return answer(request, *found)


@reading
def harnesses(request: Request) -> Response:
    return answer(request, encode("harnesses", (seams(request).services.harnesses or Harnesses((), {})).as_json()))


def routes(api: Api) -> list[ApiRoute]:
    def timed(route: str) -> Callable[[Request, Arrival], AbstractContextManager[Any]]:
        slow = SlowReads(route, api.services.slow_read_s)
        return lambda request, arrival: slow.watch(query(request).get("q", [""])[0], arrival)

    searching = frozenset({"before", "finished_within_days", "label", "limit", "q"})
    return [
        ReadRoute("/doctor", doctor),
        ReadRoute("/health", ready),
        ReadRoute("/done", done, params=frozenset({"before", "limit", "milestone"})),
        ReadRoute("/search", search, timed("/api/search"), params=searching),
        ReadRoute("/search/similar", similar, timed("/api/search/similar"), params=searching),
        ReadRoute("/harnesses", harnesses),
    ]
