"""The board's docs: list, read, create, upsert and archive."""

from pathlib import PurePosixPath
from typing import Any

from starpulse.board.model.seam import Board
from starpulse.contracts.api.dto.requests import DocCreateRequest, DocListRequest, DocPutRequest
from starpulse.views.application.commands.guard import lan_refusal, on_lan, with_request
from starpulse.views.application.commands.revisions import lock, revised


@with_request(DocListRequest, "Listing docs")
def docs_list(request: DocListRequest, board: Board) -> tuple[int, dict[str, Any]]:
    """The docs among the ids `request` names, in that order and bodies left out, an archived doc included: the HTTP
    status and JSON body. A doc the board has none of is skipped, and no ids is refused, since nothing needs every doc."""
    if not request.ids:
        return 400, {"error": 'name the docs: {"ids": ["doc-1", "doc-2"]}'}
    found = (board.read_doc(doc) for doc in request.ids)
    return 200, {"docs": [{key: value for key, value in record.items() if key != "body"} for record in found if record]}


def doc_record(board: Board, doc: str) -> tuple[int, dict[str, Any]]:
    """The record of one doc with its body and `revision`, an archived doc's included: the HTTP status and JSON body."""
    if (record := board.read_doc(doc)) is None:
        return 404, {"error": f"{doc} is not a doc"}
    return 200, {"doc": revised(record)}


@with_request(DocCreateRequest, "Adding a doc")
def create_doc(request: DocCreateRequest, board: Board) -> tuple[int, dict[str, Any]]:
    """File the doc `request` names through the board's `create_doc`: the HTTP status and JSON body, which holds the new
    doc's id. Only the title is required."""
    title = request.title
    if not title.strip():
        return 400, {"error": 'an add needs {"title": "<text>"}'}
    written = board.create_doc(title, request.model_dump(exclude_unset=True, exclude={"title"}))
    if not written.ok:  # the writer refuses a detail it cannot store, or a title it cannot file
        return 400, {"error": written.output, "skill": written.skill}
    return 201, {"doc": written.output}


@with_request(DocPutRequest, "Writing a doc")
def put_doc(request: DocPutRequest, doc: str, board: Board) -> tuple[int, dict[str, Any]]:
    """Upsert the fields `request` names into a doc, if the doc still reads `base`: the HTTP status and JSON body.

    A stale `base`, or a write to an archived doc that does not restore it, is 409. `archived: false` returns an
    archived doc to `folder` first; a `folder` on an open doc moves it there. `changed` names what the write changed; one that changes nothing writes nothing.
    """
    with lock:
        if (current := board.read_doc(doc)) is None:
            return 404, {"error": f"{doc} is not a doc"}
        ident = current["id"]
        if request.base != revised(current)["revision"]:
            return 409, {"error": f"{ident} changed since its revision {request.base}: read it again"}
        restoring = request.archived is False and current["archived"]
        if current["archived"] and not restoring:
            return 409, {"error": f"{ident} is archived: PUT it with archived false to restore it"}
        if request.folder is not None and request.archived is False and not restoring:
            return 400, {"error": "a folder names where a restored doc goes: an open doc has none to restore"}
        changed = ["archived"] if restoring else []
        if restoring and not (written := board.restore_doc(ident, request.folder or "")).ok:
            return 409, {"error": written.output, "skill": written.skill}
        if request.folder is not None and not restoring:
            if not (written := board.move_doc(ident, request.folder)).ok:
                return 409, {"error": written.output, "skill": written.skill}
            here = PurePosixPath(current["path"]).parent.as_posix()
            if request.folder.strip("/") != ("" if here == "." else here):
                changed.append("folder")
        fields = request.model_dump(exclude_unset=True, exclude={"base", "archived", "folder"})
        if todo := {field: value for field, value in fields.items() if value != current.get(field)}:
            if not (written := board.edit_doc(ident, todo)).ok:
                return 409, {"error": written.output, "skill": written.skill}
            changed += list(todo)
    return 200, {"doc": ident, "changed": changed}


def delete_doc(source: str, doc: str, board: Board) -> tuple[int, dict[str, Any]]:
    """Archive the open doc `doc` through the board's `archive_doc`: the HTTP status and JSON body."""
    if not on_lan(source):
        return lan_refusal("Archiving a doc")
    with lock:
        if (current := board.read_doc(doc)) is None or current["archived"]:
            return 404, {"error": f"{doc} is not an open doc"}
        written = board.archive_doc(current["id"])
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"doc": current["id"]}
