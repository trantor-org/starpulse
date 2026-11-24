"""Machines.

- `POST /api/machines`: every machine the board draws with its `type` and `parents`.
- `GET /api/machines/{name}`: one machine's declared config; the Board's also holds each lane's surface.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole_body
from starpulse.views.application.commands.machines import machine_record, machines_list
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def record(request: Request) -> Response:
    api = seams(request)
    status, body = machine_record(api.feed.machines, request.path_params["name"], api.services.lanes)
    return answer(request, encode("machine", body), status)


def routes(api: Api) -> list[ApiRoute]:
    return [
        ReadRoute("/machines/{name}", record),
        WriteRoute(
            "/machines",
            ("POST",),
            guarded("machines", whole_body(lambda client, raw: machines_list(client, raw, api.feed.machines))),
        ),
    ]
