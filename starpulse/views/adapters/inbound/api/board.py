"""What the page asks of the Board and its deployment besides the snapshot.

- `GET /api/doctor`: the contract report.
- `GET /api/ready`: 200 when the server can serve the board, 503 naming each component that is not ready.
- `GET /api/runs`: every runs workflow with its latest run, and the error a runs instance reported.
- `GET /api/machines`, `/api/done`, `/api/search`: the lifecycle machines, the Done lane and a search of the tasks.
- `GET /api/search/similar`: `/api/search` that waits to embed a new query, for a caller that needs the tasks nearest
  in meaning, not an answer within a budget.
- `GET /api/harnesses`: the harnesses a session may start on.
"""

from starlette.requests import Request
from starlette.responses import Response

from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.views.adapters.inbound.api.answering import answer, query, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute
from starpulse.views.application.queries.responses import done_response, machines_response, search_response
from starpulse.views.model.encoding import encode


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
def runs(request: Request) -> Response:
    return answer(request, encode("runs", seams(request).feed.run_list()))


@reading
def machines(request: Request) -> Response:
    api = seams(request)
    return answer(request, *machines_response(api.feed, query(request), api.services.lanes))


@reading
def done(request: Request) -> Response:
    api = seams(request)
    return answer(request, *done_response(api.feed, api.board.read, query(request)))


@reading
def search(request: Request) -> Response:
    return answer(request, *search_response(seams(request).services.search, query(request)))


@reading
def similar(request: Request) -> Response:
    return answer(request, *search_response(seams(request).services.search, query(request), wait=True))


@reading
def harnesses(request: Request) -> Response:
    return answer(request, encode("harnesses", (seams(request).services.harnesses or Harnesses((), {})).as_json()))


routes: list[ApiRoute] = [
    ReadRoute("/doctor", doctor),
    ReadRoute("/ready", ready),
    ReadRoute("/runs", runs),
    ReadRoute("/machines", machines, params=frozenset({"before", "limit", "open"})),
    ReadRoute("/done", done, params=frozenset({"before", "limit"})),
    ReadRoute("/search", search, params=frozenset({"before", "finished_within_days", "label", "limit", "q"})),
    ReadRoute("/search/similar", similar, params=frozenset({"before", "finished_within_days", "label", "limit", "q"})),
    ReadRoute("/harnesses", harnesses),
]
