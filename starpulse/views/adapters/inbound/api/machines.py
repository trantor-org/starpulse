"""Machines.

- `POST /api/machines`: every machine the board draws: its states, transitions, drawing and `roles`.
- `GET /api/machines/{name}`: one machine's declared config and the `hash` of its stored version; the Board's also
  holds each lane's surface.
- `PUT /api/machines`: add a machine to the store (201; 409 taken; 422 bad definition).
- `PUT /api/machines/{name}`: write a new version over a `base` hash, with optional `policy` rows (409 stale base or
  stranded task; 404 unknown; 422 bad).
- `DELETE /api/machines/{name}`: retire a machine, keeping every version (409 for the Board's or a submachine).
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, client, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole, whole_body
from starpulse.views.application.commands.machines import (
    create_machine,
    delete_machine,
    machine_record,
    machines_list,
    put_machine,
)
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def record(request: Request) -> Response:
    api = seams(request)
    status, body = machine_record(api.feed.machines, request.path_params["name"], api.services.lanes, api.services.machines)
    return answer(request, encode("machine", body), status)


def routes(api: Api) -> list[ApiRoute]:
    store = api.services.machines
    return [
        ReadRoute("/machines/{name}", record),
        WriteRoute(
            "/machines",
            ("POST",),
            guarded("machines", whole_body(lambda client, raw: machines_list(client, raw, api.feed.machines, api.feed.roles.wire()))),
        ),
        WriteRoute("/machines", ("PUT",), guarded("machine_create", whole_body(lambda who, raw: create_machine(who, raw, store)))),
        WriteRoute(
            "/machines/{name}",
            ("PUT",),
            guarded("machine_put", lambda request: put_machine(client(request), whole(request), request.path_params["name"], store)),
        ),
        WriteRoute(
            "/machines/{name}",
            ("DELETE",),
            guarded("machine_retire", lambda request: delete_machine(client(request), request.path_params["name"], store)),
        ),
    ]
