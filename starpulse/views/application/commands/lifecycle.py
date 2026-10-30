"""Park a task for a typed reason and move it to Review with the evidence it ships."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import yaml

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.markdown import section_set
from starpulse.board.model.seam import (
    TaskEditor,
    TaskReader,
)
from starpulse.contracts.api.dto.requests import (
    ParkRequest,
    ReviewRequest,
)
from starpulse.views.application.commands.guard import (
    EDIT_LOCK,
    Who,
    held_task,
    not_held,
    record_written,
    who_of,
    with_request,
)
from starpulse.views.application.commands.moves import column_status, move_refusal

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


class _RefusalError(Exception):
    """A lifecycle write refused before it is made: the HTTP status and JSON body to answer with."""

    def __init__(self, status: int, body: dict[str, str]) -> None:
        super().__init__(body["error"])
        self.answer = (status, body)


def _lifecycle_edit(
    feed: BoardFeed,
    task: str,
    column: str,
    who: Who,
    comment: str,
    read: TaskReader,
    edit: TaskEditor,
    plan: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    """Move `task` to `column` in one `edit` of the fields `plan` draws from its current record, as `who`.

    The board's rules judge the record the edit makes, so a refusal returns their reason and skill with nothing written;
    a `plan` that refuses raises `_RefusalError`.
    """
    with EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        try:
            changes = {"status": column_status(column), **plan(current)}
        except _RefusalError as refusal:
            return refusal.answer
        written = record_written(feed, task, who, lambda: edit(task, changes, comment, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "to": column}


def _wait_on_tasks(feed: BoardFeed, task: str, current: dict[str, Any], ids: Any) -> dict[str, Any]:
    """The edit that makes the task wait on the tasks `ids` names, kept after the dependencies it has.

    An id `TASK-N#K` waits on the task for its criterion K alone: the edit records that need beside the dependency,
    and the task actor releases the dependent once the criterion is checked, whatever the task still has open."""
    if not (isinstance(ids, list) and ids and all(isinstance(name, str) and name.strip() for name in ids)):
        raise _RefusalError(400, {"error": 'untilTask needs a non-empty list of task ids: {"untilTask": ["TASK-N"]}'})
    named = list(dict.fromkeys(name.strip() for name in ids))
    waits = list(dict.fromkeys(name.partition("#")[0] for name in named))
    for name in waits:
        if name.casefold() == task.casefold():
            raise _RefusalError(409, {"error": f"{task} cannot wait on itself"})
        if feed.is_done(name):
            raise _RefusalError(409, {"error": f"{name} is already Done: there is nothing to wait for"})
        if held_task(feed, name) is None:
            raise _RefusalError(*not_held(feed, name))
    needs = [name for name in named if "#" in name]
    for need in needs:
        _open_criterion(feed, need)
    return {
        "dependencies": list(dict.fromkeys([*current["dependencies"], *waits])),
        **({"dependencyNeeds": list(dict.fromkeys([*current.get("dependencyNeeds", []), *needs]))} if needs else {}),
    }


def _open_criterion(feed: BoardFeed, need: str) -> None:
    """Refuse the dependency need `TASK-N#K` unless the task has a criterion K that is not yet checked."""
    name, _, number = need.partition("#")
    criteria = (feed.task(name) or {}).get("criteria", [])
    if not (number.isdigit() and 0 < int(number) <= len(criteria)):
        raise _RefusalError(409, {"error": f"{name} has no criterion #{number} to wait for"})
    if criteria[int(number) - 1]["checked"]:
        raise _RefusalError(
            409, {"error": f"{name} criterion #{number} is already checked: there is nothing to wait for"}
        )


def _wait_on_criteria(feed: BoardFeed, task: str, current: dict[str, Any], found: Any) -> dict[str, Any]:
    """The edit that makes the task wait for the start criteria `found`, which replace those it has.

    Only the shape is judged here: what a criterion observes is for the client that evaluates it.
    """
    if not (
        isinstance(found, list)
        and found
        and all(isinstance(item, dict) and all(_nonblank(item.get(key)) for key in ("id", "kind")) for item in found)
        and len({item["id"] for item in found}) == len(found)
    ):
        raise _RefusalError(
            400, {"error": 'until needs a non-empty list of criteria, each with a unique "id" and a "kind"'}
        )
    if open_ := [name for name in current["dependencies"] if not feed.is_done(name)]:
        raise _RefusalError(
            409,
            {"error": f"{task} already waits on {', '.join(open_)}; a task is gated by one reason, never both"},
        )
    block = "```yaml\n" + yaml.safe_dump({"start_criteria": found}, sort_keys=False) + "```"
    return {
        "description": section_set(current["description"], "Start Criteria", block),
        **({"dependencies": []} if current["dependencies"] else {}),  # Done dependencies gate nothing
    }


def _wait_on_operator(current: dict[str, Any], reason: Any) -> dict[str, Any]:
    """The edit that records `reason` as what only the operator can clear."""
    if not _nonblank(reason):
        raise _RefusalError(400, {"error": "operator needs the reason, in text, that only the operator can clear"})
    return {"description": section_set(current["description"], "Needs attention", reason)}


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


_BAD_PARK = {
    "error": 'a park needs exactly one reason: "untilTask" (task ids that must reach Done), "until" (criteria, each an '
    'object with an "id" and a "kind") or "operator" (text)'
}
_PARK_REASONS = ("untilTask", "until", "operator")


def _park_lane(feed: BoardFeed, reason: str) -> str | None:
    """The lane a park for `reason` moves to: where a task waits on a fact, or on the operator."""
    return feed.roles.attention if reason == "operator" else feed.roles.waiting


@with_request(ParkRequest, "Parking a task")
def park_task(
    request: ParkRequest, feed: BoardFeed, read: TaskReader | None, edit: TaskEditor | None
) -> tuple[int, dict[str, Any]]:
    """Park the In Progress task `request` names for the one reason it names: the HTTP status and JSON body.

    The reason picks the lane and writes its gate in the same edit: `untilTask` adds dependencies (a `TASK-N#K` entry also records the criterion needed) and `until` writes the
    Start Criteria block, both to Waiting, and `operator` writes the Needs attention section to Needs attention. The
    machine must offer the writer that lane, and the board's rules judge the record the edit makes.
    """
    task, comment, who = request.task, request.comment or "", who_of(request)
    reasons = [key for key in _PARK_REASONS if key in request.model_fields_set]
    if len(reasons) != 1:
        return 400, _BAD_PARK
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    if agent["state"] != feed.roles.working:
        return 409, {"error": f"only an In Progress task can be parked: {task} is {agent['state']}"}
    reason = reasons[0]
    column, value = _park_lane(feed, reason), getattr(request, reason)
    if column is None:
        return 409, {"error": f"this board's machine has no lane to park {task} in for {reason}"}
    if (refused := move_refusal(agent, task, column, who)) is not None:
        return refused
    plans = {
        "untilTask": lambda current: _wait_on_tasks(feed, task, current, value),
        "until": lambda current: _wait_on_criteria(feed, task, current, value),
        "operator": lambda current: _wait_on_operator(current, value),
    }
    return _lifecycle_edit(feed, task, column, who, comment, read, edit, plans[reason])


_BAD_REVIEW = {"error": "references must each be a nonblank pull request link"}


@with_request(ReviewRequest, "Reviewing a task")
def review_task(
    request: ReviewRequest, feed: BoardFeed, read: TaskReader | None, edit: TaskEditor | None
) -> tuple[int, dict[str, Any]]:
    """Move the task `request` names to Review with the evidence it names: the HTTP status and JSON body.

    The `references` join those the task has and a non-blank `summary` becomes its final summary, in the one edit that
    makes the move. The board's rules judge the record that edit makes, so a task whose evidence they refuse stays where
    it is and the answer carries their reason and skill.
    """
    task, links, summary = request.task, request.references or [], request.summary or ""
    if not all(_nonblank(link) for link in links):
        return 400, _BAD_REVIEW
    comment, who = request.comment or "", who_of(request)
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    review = feed.roles.review
    if review is None:
        return 409, {"error": f"this board's machine has no lane to move {task} to for review"}
    if (refused := move_refusal(agent, task, review, who)) is not None:
        return refused

    def plan(current: dict[str, Any]) -> dict[str, Any]:
        references = list(dict.fromkeys([*current["references"], *(link.strip() for link in links)]))
        return {
            **({"references": references} if references != current["references"] else {}),
            **({"finalSummary": summary.strip()} if summary.strip() else {}),
        }

    return _lifecycle_edit(feed, task, review, who, comment, read, edit, plan)
