"""The window of the flow history the Board keeps.

- `GET`, `PUT` and `DELETE` `/api/history-window`: the window the history covers, set or reset by a write.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, client, on_loop, on_worker, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole
from starpulse.views.application.commands.settings import history_window
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


async def read_window(request: Request) -> Response:
    def read() -> Response:
        status, body = history_window(client(request), "GET", b"", seams(request).window)
        return answer(request, encode("window", body), status)

    return on_loop(request, read) or await on_worker(request, read)


def routes(api: Api) -> list[ApiRoute]:
    window = api.window

    def write_window(request: Request) -> tuple[int, dict]:
        return history_window(client(request), request.method, whole(request), window)

    return [
        ReadRoute("/history-window", read_window),
        WriteRoute("/history-window", ("PUT", "DELETE"), guarded("window", write_window)),
    ]
