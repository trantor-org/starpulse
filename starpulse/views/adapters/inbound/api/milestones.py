"""Milestones.

- `GET /api/milestones`, `/api/milestones/{id}`: the milestones, and one.
- `POST /api/milestones`, `/api/milestones/edit`, `/api/milestones/archive`: create, edit and archive one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, Request, Response, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole_body
from starpulse.views.application.commands.milestones import (
    archive_milestone,
    create_milestone,
    edit_milestone,
    milestone_record,
    milestones_list,
)
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


def routes(api: Api) -> list[ApiRoute]:
    board = api.board

    def record(request: Request) -> Response:
        status, body = milestone_record(board, request.path_params["id"])
        return Response(encode("milestone", body), status)

    def listed(request: Request) -> Response:
        status, body = milestones_list(board)
        return Response(encode("milestones", body), status)

    return [
        ReadRoute("/milestones/{id:path}", record),
        ReadRoute("/milestones", listed),
        WriteRoute(
            "/milestones",
            ("POST",),
            guarded("milestone_create", whole_body(lambda client, raw: create_milestone(client, raw, board))),
        ),
        WriteRoute(
            "/milestones/edit",
            ("POST",),
            guarded("milestone_edit", whole_body(lambda client, raw: edit_milestone(client, raw, board))),
        ),
        WriteRoute(
            "/milestones/archive",
            ("POST",),
            guarded("milestone_archive", whole_body(lambda client, raw: archive_milestone(client, raw, board))),
        ),
    ]
