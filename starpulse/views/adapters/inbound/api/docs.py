"""Docs.

- `POST /api/docs`: the docs named, bodies left out. `GET /api/docs/{id}`: one doc with its body and `revision`.
- `PUT /api/docs`: create one. `PUT /api/docs/{id}`: write one over the `base` it read, or restore it.
- `DELETE /api/docs/{id}`: archive one.
"""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from starpulse.views.adapters.inbound.api.answering import answer, client, reading, seams
from starpulse.views.adapters.inbound.api.table import ApiRoute, ReadRoute, WriteRoute
from starpulse.views.adapters.inbound.api.writing import guarded, whole, whole_body
from starpulse.views.application.commands.docs import create_doc, delete_doc, doc_record, docs_list, put_doc
from starpulse.views.model.encoding import encode

if TYPE_CHECKING:  # annotation only
    from starpulse.views.adapters.inbound.api.routing import Api


@reading
def record(request: Request) -> Response:
    status, body = doc_record(seams(request).board, request.path_params["id"])
    return answer(request, encode("doc", body), status)


def routes(api: Api) -> list[ApiRoute]:
    board = api.board

    return [
        ReadRoute("/docs/{id:path}", record),
        WriteRoute("/docs", ("POST",), guarded("docs", whole_body(lambda client, raw: docs_list(client, raw, board)))),
        WriteRoute("/docs", ("PUT",), guarded("doc_create", whole_body(lambda client, raw: create_doc(client, raw, board)))),
        WriteRoute(
            "/docs/{id:path}",
            ("PUT",),
            guarded("doc_put", lambda request: put_doc(client(request), whole(request), request.path_params["id"], board)),
        ),
        WriteRoute(
            "/docs/{id:path}",
            ("DELETE",),
            guarded("doc_archive", lambda request: delete_doc(client(request), request.path_params["id"], board)),
        ),
    ]
