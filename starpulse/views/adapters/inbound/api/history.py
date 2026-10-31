"""The flow history and the window of it the Board keeps.

- `GET /api/history`: the flow history, filtered by the query.
- `GET`, `PUT` and `DELETE` `/api/history-window`: the window the history covers, set or reset by a write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, client, query, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole
from starpulse.views.application.commands.settings import history_window
from starpulse.views.application.queries.responses import history_response
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def history(request: Request) -> Response:
    api = seams(request)
    feed = api.feed
    return answer(request, *history_response(api.history, query(request), feed.machines.keys(), feed.keys, api.clock))


@reading
def read_window(request: Request) -> Response:
    status, body = history_window(client(request), "GET", b"", seams(request).window)
    return answer(request, encode("window", body), status)


def routes(api: Api) -> list[ApiRoute]:
    window = api.window

    def write_window(request: Request) -> tuple[int, dict]:
        return history_window(client(request), request.method, whole(request), window)

    return [
        ReadRoute("/history", history),
        ReadRoute("/history-window", read_window),
        WriteRoute("/history-window", ("PUT", "DELETE"), guarded("window", write_window)),
    ]
