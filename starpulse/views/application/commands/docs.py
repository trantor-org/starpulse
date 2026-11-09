"""The board's docs: list, read, create, edit, archive and restore."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from starpulse.board.model.seam import (
    Board,
)
from starpulse.contracts.api.dto.requests import (
    DocArchiveRequest,
    DocCreateRequest,
    DocEditRequest,
    DocRestoreRequest,
)
from starpulse.views.application.commands.guard import with_request

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


def docs_list(board: Board | None) -> tuple[int, dict[str, Any]]:
    """The open docs the board keeps, bodies left out: the HTTP status and JSON body. Reading is not LAN-limited."""
    if board is None or board.docs is None:
        return 404, {"error": "this board keeps no docs"}
    return 200, {"docs": board.docs()}


def doc_record(board: Board | None, doc: str) -> tuple[int, dict[str, Any]]:
    """The record, body included, of one open doc: the HTTP status and JSON body."""
    if board is None or board.read_doc is None:
        return 404, {"error": "this board keeps no docs"}
    if (record := board.read_doc(doc)) is None:
        return 404, {"error": f"{doc} is not an open doc"}
    return 200, {"doc": record}


@with_request(DocCreateRequest, "Adding a doc")
def create_doc(request: DocCreateRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """File the doc `request` names through the board's `create_doc`: the HTTP status and JSON body, which holds the new
    doc's id. Only the title is required."""
    title = request.title
    if not title.strip():
        return 400, {"error": 'an add needs {"title": "<text>"}'}
    if board is None or board.create_doc is None:
        return 404, {"error": "this board does not create docs"}
    written = board.create_doc(title, request.model_dump(exclude_unset=True, exclude={"title"}))
    if not written.ok:  # the writer refuses a detail it cannot store, or a title it cannot file
        return 400, {"error": written.output, "skill": written.skill}
    return 201, {"doc": written.output}


@with_request(DocEditRequest, "Editing a doc")
def edit_doc(request: DocEditRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Apply the `changes` `request` names to a doc through the board's `edit_doc`: the HTTP status and JSON body.
    `changed` names the fields whose value the edit changed; an edit that changes none writes nothing."""
    doc, changes = request.doc, request.changes
    if not changes:
        return 400, {"error": 'an edit needs {"doc": "doc-N", "changes": {...}}'}
    if board is None or board.read_doc is None or board.edit_doc is None:
        return 404, {"error": "this board does not edit docs"}
    if (current := board.read_doc(doc)) is None:
        return 404, {"error": f"{doc} is not an open doc"}
    if not (todo := {field: value for field, value in changes.items() if value != current.get(field)}):
        return 200, {"doc": doc, "changed": []}
    written = board.edit_doc(doc, todo)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"doc": doc, "changed": list(todo)}


@with_request(DocArchiveRequest, "Archiving a doc")
def archive_doc(request: DocArchiveRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Archive the doc `request` names through the board's `archive_doc`: the HTTP status and JSON body."""
    doc = request.doc
    if board is None or board.read_doc is None or board.archive_doc is None:
        return 404, {"error": "this board does not archive docs"}
    if board.read_doc(doc) is None:
        return 404, {"error": f"{doc} is not an open doc"}
    written = board.archive_doc(doc)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"doc": doc}


@with_request(DocRestoreRequest, "Restoring a doc")
def restore_doc(request: DocRestoreRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Return the archived doc `request` names to the folder it names under the board's docs through the board's
    `restore_doc`: the HTTP status and JSON body.

    The writer owns every other refusal (no archived file, the id already open, the destination taken, a folder that is
    not a path of plain names), which answers 409 with its reason.
    """
    doc, folder = request.doc, request.folder or ""
    if board is None or board.restore_doc is None:
        return 404, {"error": "this board does not restore docs"}
    written = board.restore_doc(doc, folder)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"doc": doc}
