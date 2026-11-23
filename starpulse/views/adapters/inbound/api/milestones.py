"""Milestones.

- `POST /api/milestones`: the open milestones. `GET /api/milestones/{id}`: one milestone with its `revision`.
- `PUT /api/milestones`: create one. `PUT /api/milestones/{id}`: write one over the `base` it read.
- `DELETE /api/milestones/{id}`: archive one.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, client, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole, whole_body
from starpulse.views.application.commands.milestones import (
    create_milestone,
    delete_milestone,
    milestone_record,
    milestones_list,
    put_milestone,
)
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def record(request: Request) -> Response:
    status, body = milestone_record(seams(request).board, request.path_params["id"])
    return answer(request, encode("milestone", body), status)


def routes(api: Api) -> list[ApiRoute]:
    board = api.board

    return [
        ReadRoute("/milestones/{id:path}", record),
        WriteRoute(
            "/milestones",
            ("POST",),
            guarded("milestones", whole_body(lambda client, raw: milestones_list(client, raw, board))),
        ),
        WriteRoute(
            "/milestones",
            ("PUT",),
            guarded("milestone_create", whole_body(lambda client, raw: create_milestone(client, raw, board))),
        ),
        WriteRoute(
            "/milestones/{id:path}",
            ("PUT",),
            guarded(
                "milestone_put",
                lambda request: put_milestone(client(request), whole(request), request.path_params["id"], board),
            ),
        ),
        WriteRoute(
            "/milestones/{id:path}",
            ("DELETE",),
            guarded(
                "milestone_archive", lambda request: delete_milestone(client(request), request.path_params["id"], board)
            ),
        ),
    ]
