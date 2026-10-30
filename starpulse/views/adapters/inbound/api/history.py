"""The flow history and the window of it the Board keeps.

- `GET /api/history`: the flow history, filtered by the query.
- `GET`, `PUT` and `DELETE` `/api/history-window`: the window the history covers, set or reset by a write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, Request, Response, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole
from starpulse.views.application.commands.settings import history_window
from starpulse.views.application.queries.responses import history_response
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.neutral import WriteRequest
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    feed, window = api.feed, api.window

    def history(request: Request) -> Response:
        return Response(
            *history_response(api.history, parse_qs(request.query), feed.machines.keys(), feed.keys, api.clock)
        )

    def read_window(request: Request) -> Response:
        status, body = history_window(request.client, "GET", b"", window)
        return Response(encode("window", body), status)

    def write_window(request: WriteRequest) -> tuple[int, dict]:
        return history_window(request.client, request.method, whole(request), window)

    return [
        ReadRoute("/history", history),
        ReadRoute("/history-window", read_window),
        WriteRoute("/history-window", ("PUT", "DELETE"), guarded("window", write_window)),
    ]
