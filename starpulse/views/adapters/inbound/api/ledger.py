"""A Ledger's rows.

- `GET /api/ledger/{event}/events`: the stream of an event's newest rows, then each row that changes.
- `GET /api/ledger/{event}`: an event's rows, paged by the query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, Request, Response, StreamRoute
from starpulse.views.application.queries.responses import _error, ledger_response

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    feed = api.feed

    def ledger(request: Request) -> Response:
        event, _, tail = request.path_params["rest"].partition("/")
        if tail:
            return Response(_error(f"unknown route {request.path}"), 404)
        return Response(*ledger_response(feed, event, parse_qs(request.query)))

    # The stream first: its path is also the read's, whose `{rest:path}` takes the `/events` too.
    return [
        StreamRoute("/ledger/{rest:path}/events", api.streams.ledger_rows),
        ReadRoute("/ledger/{rest:path}", ledger),
    ]
