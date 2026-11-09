"""What the page asks of the Board and its deployment besides the snapshot.

- `GET /api/doctor`: the contract report.
- `GET /api/machines`, `/api/done`, `/api/search`: the lifecycle machines, the Done lane and a search of the tasks.
- `GET /api/harnesses`: the harnesses a session may start on.
"""

from __future__ import annotations

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
def machines(request: Request) -> Response:
    return answer(request, *machines_response(seams(request).feed, query(request)))


@reading
def done(request: Request) -> Response:
    api = seams(request)
    return answer(request, *done_response(api.feed, api.board.read, query(request)))


@reading
def search(request: Request) -> Response:
    return answer(request, *search_response(seams(request).services.search, query(request)))


@reading
def harnesses(request: Request) -> Response:
    return answer(request, encode("harnesses", (seams(request).services.harnesses or Harnesses((), {})).as_json()))


routes: list[ApiRoute] = [
    ReadRoute("/doctor", doctor),
    ReadRoute("/machines", machines),
    ReadRoute("/done", done),
    ReadRoute("/search", search),
    ReadRoute("/harnesses", harnesses),
]
