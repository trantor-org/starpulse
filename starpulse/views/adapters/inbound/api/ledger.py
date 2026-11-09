"""A Ledger's rows.

- `GET /api/ledger/{event}/events`: the stream of an event's newest rows, then each row that changes.
- `GET /api/ledger/{event}`: an event's rows, paged by the query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, query, reading, seams, target
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, StreamRoute
from starpulse.views.adapters.inbound.api.streams import streaming
from starpulse.views.application.queries.responses import _error, ledger_response

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def ledger(request: Request) -> Response:
    event, _, tail = request.path_params["rest"].partition("/")
    if tail:
        return answer(request, _error(f"unknown route {target(request)}"), 404)
    return answer(request, *ledger_response(seams(request).feed, event, query(request)))


def routes(api: Api) -> list[ApiRoute]:
    # The stream first: its path is also the read's, whose `{rest:path}` takes the `/events` too.
    return [
        StreamRoute("/ledger/{rest:path}/events", streaming(api.streams.ledger_rows)),
        ReadRoute("/ledger/{rest:path}", ledger),
    ]
