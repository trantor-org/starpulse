"""What the page asks of the Board and its deployment besides the snapshot.

- `GET /api/doctor`: the contract report.
- `GET /api/machines`, `/api/done`, `/api/search`: the lifecycle machines, the Done lane and a search of the tasks.
- `GET /api/harnesses`: the harnesses a session may start on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from starpulse.harness_telemetry.model.harnesses import Harnesses
from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, Request, Response
from starpulse.views.application.queries.responses import done_response, machines_response, search_response
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    feed, services = api.feed, api.services
    harnesses = Response(encode("harnesses", (services.harnesses or Harnesses((), {})).as_json()))

    def doctor(request: Request) -> Response:
        return Response(encode("doctor", services.contract() if services.contract else {"ok": True, "checks": []}))

    def machines(request: Request) -> Response:
        return Response(*machines_response(feed, parse_qs(request.query)))

    def done(request: Request) -> Response:
        return Response(*done_response(feed, api.board.read, parse_qs(request.query)))

    def search(request: Request) -> Response:
        return Response(*search_response(services.search, parse_qs(request.query)))

    return [
        ReadRoute("/doctor", doctor),
        ReadRoute("/machines", machines),
        ReadRoute("/done", done),
        ReadRoute("/search", search),
        ReadRoute("/harnesses", lambda request: harnesses),
    ]
