"""Docs.

- `GET /api/docs`, `/api/docs/{id}`: the docs, and one.
- `POST /api/docs`, `/api/docs/edit`, `/api/docs/archive`, `/api/docs/restore`: create, edit, archive and restore one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, reading, seams
from starpulse.views.adapters.inbound.api.neutral import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole_body
from starpulse.views.application.commands.docs import (
    archive_doc,
    create_doc,
    doc_record,
    docs_list,
    edit_doc,
    restore_doc,
)
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def record(request: Request) -> Response:
    status, body = doc_record(seams(request).board, request.path_params["id"])
    return answer(request, encode("doc", body), status)


@reading
def listed(request: Request) -> Response:
    status, body = docs_list(seams(request).board)
    return answer(request, encode("docs", body), status)


def routes(api: Api) -> list[ApiRoute]:
    board = api.board

    return [
        ReadRoute("/docs/{id:path}", record),
        ReadRoute("/docs", listed),
        WriteRoute(
            "/docs", ("POST",), guarded("doc_create", whole_body(lambda client, raw: create_doc(client, raw, board)))
        ),
        WriteRoute(
            "/docs/edit", ("POST",), guarded("doc_edit", whole_body(lambda client, raw: edit_doc(client, raw, board)))
        ),
        WriteRoute(
            "/docs/archive",
            ("POST",),
            guarded("doc_archive", whole_body(lambda client, raw: archive_doc(client, raw, board))),
        ),
        WriteRoute(
            "/docs/restore",
            ("POST",),
            guarded("doc_restore", whole_body(lambda client, raw: restore_doc(client, raw, board))),
        ),
    ]
