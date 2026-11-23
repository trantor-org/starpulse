"""The board's milestones: list, read, create, upsert and archive."""

from typing import Any

from starpulse.board.model.seam import Board
from starpulse.contracts.api.dto.requests import MilestoneCreateRequest, MilestoneListRequest, MilestonePutRequest
from starpulse.views.application.commands.guard import lan_refusal, on_lan, with_request
from starpulse.views.application.commands.revisions import lock, revised


@with_request(MilestoneListRequest, "Listing milestones")
def milestones_list(request: MilestoneListRequest, board: Board) -> tuple[int, dict[str, Any]]:
    """The open milestones the board keeps, each with its `revision`: the HTTP status and JSON body."""
    return 200, {"milestones": [revised(record) for record in board.milestones()]}


def milestone_record(board: Board, milestone: str) -> tuple[int, dict[str, Any]]:
    """The record of one milestone with its `revision`, an archived milestone's included: the HTTP status and JSON body."""
    if (record := board.read_milestone(milestone)) is None:
        return 404, {"error": f"{milestone} is not a milestone"}
    return 200, {"milestone": revised(record)}


@with_request(MilestoneCreateRequest, "Adding a milestone")
def create_milestone(request: MilestoneCreateRequest, board: Board) -> tuple[int, dict[str, Any]]:
    """Open the milestone `request` names through the board's `create_milestone`: the HTTP status and JSON body, which
    holds the new milestone's id. Only the title is required."""
    title = request.title
    if not title.strip():
        return 400, {"error": 'an add needs {"title": "<text>"}'}
    written = board.create_milestone(title, request.model_dump(exclude_unset=True, exclude={"title"}))
    if not written.ok:  # the writer refuses a detail it cannot store, or a title it cannot file
        return 400, {"error": written.output, "skill": written.skill}
    return 201, {"milestone": written.output}


@with_request(MilestonePutRequest, "Writing a milestone")
def put_milestone(request: MilestonePutRequest, milestone: str, board: Board) -> tuple[int, dict[str, Any]]:
    """Upsert the fields `request` names into a milestone, if it still reads `base`: the HTTP status and JSON body.

    A stale `base`, or a write to an archived milestone, is 409. `changed` names what the write changed; one that
    changes nothing writes nothing.
    """
    with lock:
        if (current := board.read_milestone(milestone)) is None:
            return 404, {"error": f"{milestone} is not a milestone"}
        if request.base != revised(current)["revision"]:
            return 409, {"error": f"{milestone} changed since its revision {request.base}: read it again"}
        if current["archived"]:
            return 409, {"error": f"{milestone} is archived"}
        fields = request.model_dump(exclude_unset=True, exclude={"base"})
        if not (todo := {field: value for field, value in fields.items() if value != current.get(field)}):
            return 200, {"milestone": milestone, "changed": []}
        written = board.edit_milestone(milestone, todo)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"milestone": milestone, "changed": list(todo)}


def delete_milestone(source: str, milestone: str, board: Board) -> tuple[int, dict[str, Any]]:
    """Archive the open milestone `milestone` through the board's `archive_milestone`: the HTTP status and JSON body."""
    if not on_lan(source):
        return lan_refusal("Archiving a milestone")
    with lock:
        if (current := board.read_milestone(milestone)) is None or current["archived"]:
            return 404, {"error": f"{milestone} is not an open milestone"}
        written = board.archive_milestone(milestone)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"milestone": milestone}
