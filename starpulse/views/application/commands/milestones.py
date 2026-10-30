"""The board's milestones: list, read, create, edit and archive."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from starpulse.board.model.seam import (
    Board,
)
from starpulse.contracts.api.dto.requests import (
    MilestoneArchiveRequest,
    MilestoneCreateRequest,
    MilestoneEditRequest,
)
from starpulse.views.application.commands.guard import with_request

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


def milestones_list(board: Board | None) -> tuple[int, dict[str, Any]]:
    """The open milestones the board keeps: the HTTP status and JSON body. Reading is not LAN-limited, like the snapshot."""
    if board is None or board.milestones is None:
        return 404, {"error": "this board keeps no milestones"}
    return 200, {"milestones": board.milestones()}


def milestone_record(board: Board | None, milestone: str) -> tuple[int, dict[str, Any]]:
    """The record of one open milestone: the HTTP status and JSON body."""
    if board is None or board.read_milestone is None:
        return 404, {"error": "this board keeps no milestones"}
    if (record := board.read_milestone(milestone)) is None:
        return 404, {"error": f"{milestone} is not an open milestone"}
    return 200, {"milestone": record}


@with_request(MilestoneCreateRequest, "Adding a milestone")
def create_milestone(request: MilestoneCreateRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Open the milestone `request` names through the board's `create_milestone`: the HTTP status and JSON body, which
    holds the new milestone's id. Only the title is required."""
    title = request.title
    if not title.strip():
        return 400, {"error": 'an add needs {"title": "<text>"}'}
    if board is None or board.create_milestone is None:
        return 404, {"error": "this board does not create milestones"}
    written = board.create_milestone(title, request.model_dump(exclude_unset=True, exclude={"title"}))
    if not written.ok:  # the writer refuses a detail it cannot store, or a title it cannot file
        return 400, {"error": written.output, "skill": written.skill}
    return 201, {"milestone": written.output}


@with_request(MilestoneEditRequest, "Editing a milestone")
def edit_milestone(request: MilestoneEditRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Apply the `changes` `request` names to a milestone through the board's `edit_milestone`: the HTTP status and JSON
    body. `changed` names the fields whose value the edit changed; an edit that changes none writes nothing."""
    milestone, changes = request.milestone, request.changes
    if not changes:
        return 400, {"error": 'an edit needs {"milestone": "m-N", "changes": {...}}'}
    if board is None or board.read_milestone is None or board.edit_milestone is None:
        return 404, {"error": "this board does not edit milestones"}
    if (current := board.read_milestone(milestone)) is None:
        return 404, {"error": f"{milestone} is not an open milestone"}
    if not (todo := {field: value for field, value in changes.items() if value != current.get(field)}):
        return 200, {"milestone": milestone, "changed": []}
    written = board.edit_milestone(milestone, todo)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"milestone": milestone, "changed": list(todo)}


@with_request(MilestoneArchiveRequest, "Archiving a milestone")
def archive_milestone(request: MilestoneArchiveRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Archive the milestone `request` names through the board's `archive_milestone`: the HTTP status and JSON body."""
    milestone = request.milestone
    if board is None or board.read_milestone is None or board.archive_milestone is None:
        return 404, {"error": "this board does not archive milestones"}
    if board.read_milestone(milestone) is None:
        return 404, {"error": f"{milestone} is not an open milestone"}
    written = board.archive_milestone(milestone)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"milestone": milestone}
