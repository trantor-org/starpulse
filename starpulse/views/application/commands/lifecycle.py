"""Park a task for a typed reason as a request the task actor carries out."""

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import yaml

from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.markdown import (
    ASK_REQUEST,
    WAIT_REQUEST,
    needs_attention_text,
    section_drop,
    section_set,
)
from starpulse.board.model.seam import (
    TaskEditor,
    TaskReader,
)
from starpulse.bridge.last_event import readable
from starpulse.contracts.api.dto.requests import (
    Park,
)
from starpulse.machine_engine.model.transitions import lane_id
from starpulse.views.application.commands.guard import (
    EDIT_LOCK,
    Who,
    held_task,
    not_held,
    record_written,
)
from starpulse.views.application.commands.moves import column_status

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


class _RefusalError(Exception):
    """A lifecycle write refused before it is made: the HTTP status and JSON body to answer with."""

    def __init__(self, status: int, body: dict[str, str]) -> None:
        super().__init__(body["error"])
        self.answer = (status, body)


_START_CRITERIA = re.compile(r"^## Start Criteria[ \t]*$", re.M)
_FENCE = re.compile(r"^```.*?^```", re.M | re.S)


def _lifecycle_edit(
    feed: BoardFeed,
    task: str,
    column: str,
    who: Who,
    comment: str,
    read: TaskReader,
    edit: TaskEditor,
    plan: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    moves: bool = True,
) -> tuple[int, dict[str, Any]]:
    """Move `task` to `column` in one `edit` of the fields `plan` draws from its current record, as `who`.

    With `moves` false the edit writes no lane: it is a request, and `column` is the lane the task actor is asked for.

    The board's rules judge the record the edit makes, so a refusal returns their reason and skill with nothing written;
    a `plan` that refuses raises `_RefusalError`. An edit the board accepts that leaves the task out of `column` is a 409
    naming the lane it is in, so no caller reports a move that did not happen.
    """
    with EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        try:
            changes = {**({"status": column_status(column)} if moves else {}), **plan(current)}
        except _RefusalError as refusal:
            return refusal.answer
        written = record_written(feed, task, who, lambda: edit(task, changes, comment, actor=who.actor))
        if moves and written.ok and (after := read(task)) is not None and lane_id(str(after.get("status") or "")) != column:
            return 409, {
                "error": f"{task} is still {after.get('status')}: the board accepted the write to {changes['status']} "
                "but did not move it"
            }
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
        if refused := _closed(feed, name, "there is nothing to wait for"):
            raise _RefusalError(*refused)
        if route := _route_to(feed, name, task):
            chain = " -> ".join([task, *route])
            raise _RefusalError(409, {"error": f"{task} cannot wait on {name}: it closes a cycle {chain}"})
    needs = [name for name in named if "#" in name]
    for need in needs:
        _open_criterion(feed, need)
    return {
        "dependencies": list(dict.fromkeys([*current["dependencies"], *waits])),
        **({"dependencyNeeds": list(dict.fromkeys([*current.get("dependencyNeeds", []), *needs]))} if needs else {}),
    }


def _closed(feed: BoardFeed, name: str, done: str) -> tuple[int, dict[str, Any]] | None:
    if feed.is_done(name):
        return 409, {"error": f"{name} is already Done: {done}"}
    if held_task(feed, name) is not None:
        return None
    if feed.is_archived(name):
        return 409, {"error": f"{name} is archived, so it never reaches Done"}
    return not_held(feed, name)


def _route_to(feed: BoardFeed, start: str, target: str) -> list[str] | None:
    """The chain of task ids from `start` through the dependencies each open task names to `target`, or None."""
    seen, pending = {start.casefold()}, [[start]]
    while pending:
        route = pending.pop(0)
        if route[-1].casefold() == target.casefold():
            return route
        for name in (feed.task(route[-1]) or {}).get("dependencies", ()):
            if name.casefold() not in seen:
                seen.add(name.casefold())
                pending.append([*route, name])
    return None


def blocks_refusal(feed: BoardFeed, blocks: list[str], dependencies: list[str]) -> tuple[int, dict[str, Any]] | None:
    """Why a new task depending on `dependencies` cannot block the tasks `blocks` names, or None.

    Each must be open in Ready or a lane a park on a task takes, and none may be a task the new one reaches through its
    dependencies, so the create refuses before writing anything."""
    roles = feed.roles
    lanes = (roles.ready, roles.waiting, roles.working, roles.review, roles.attention)
    for name in dict.fromkeys(blocks):
        if refused := _closed(feed, name, "there is nothing left to block"):
            return refused
        if (agent := held_task(feed, name) or {}).get("state") not in lanes:
            return 409, {"error": f"{name} is {agent['state']}: only a Ready, Waiting or started task can be blocked"}
        for dependency in dependencies:
            if route := _route_to(feed, dependency, name):
                chain = " -> ".join(["the new task", *route, "the new task"])
                return 409, {"error": f"the new task cannot block {name}: it closes a cycle {chain}"}
    return None


def block_tasks(
    feed: BoardFeed, task: str, blocks: list[str], who: Who, read: TaskReader, edit: TaskEditor
) -> dict[str, str]:
    """Add `task` to the dependencies of each task `blocks` names, after the ones it has: the error of each write the
    board refused, by task.

    A Ready task moves to Waiting in the same write, as the board's rules require of an open dependency; any other gets
    the write `park --until-task` makes, so the task actor moves a started one to Waiting."""
    column = feed.roles.waiting or ""
    unblocked = {}

    def plan(current: dict[str, Any]) -> dict[str, Any]:
        return {"dependencies": list(dict.fromkeys([*current["dependencies"], task]))} | _waiting_description(current)

    for name in dict.fromkeys(blocks):
        ready = bool(column) and (held_task(feed, name) or {}).get("state") == feed.roles.ready
        status, body = _lifecycle_edit(feed, name, column, who, f"{task} blocks this task", read, edit, plan, moves=ready)
        if status != 200:
            unblocked[name] = body["error"]
    return unblocked


def _open_criterion(feed: BoardFeed, need: str) -> None:
    """Refuse the dependency need `TASK-N#K` unless the task has a criterion K that is not yet checked."""
    name, _, number = need.partition("#")
    criteria = (feed.task(name) or {}).get("criteria", [])
    if not (number.isascii() and number.isdigit() and 0 < int(number) <= len(criteria)):
        raise _RefusalError(409, {"error": f"{name} has no criterion #{number} to wait for"})
    if criteria[int(number) - 1]["checked"]:
        raise _RefusalError(
            409, {"error": f"{name} criterion #{number} is already checked: there is nothing to wait for"}
        )


def _start_entries(item: Any) -> list[dict[str, Any]] | None:
    """The Start Criteria entries for one `until` item, or None when it is unusable.

    An item is an event subject, or an event criterion object (`{"id", "kind": "event", "query"}`) or a list of them
    written as YAML or JSON: the task actor wakes a task on events only, so any other kind is unusable.
    """
    if not isinstance(item, str):
        return None
    try:
        parsed = yaml.safe_load(item) if item.lstrip()[:1] in "{[" or "\n" in item.strip() or ": " in item else item
    except yaml.YAMLError:
        return None
    if isinstance(parsed, str):
        return [{"id": item, "kind": "event", "query": item}] if readable(item) else None
    found = parsed if isinstance(parsed, list) else [parsed]
    ok = all(
        isinstance(c, dict)
        and isinstance(c.get("id"), str)
        and c.get("kind") == "event"
        and isinstance(c.get("query"), str)
        and readable(c["query"])
        for c in found
    )
    return found if found and ok else None


def _wait_on_events(feed: BoardFeed, task: str, current: dict[str, Any], found: Any) -> dict[str, Any]:
    """The edit that makes the task wait for the first of the `found` criteria or event subjects, which replace those it waits on.

    A subject is `starpulse.<board>.alert.<rule>.<event>` or `starpulse.<board>.deploy.<component>.<event>`: the two whose
    latest event the log answers, so a wait already met releases at once. A criterion object is written as given.
    """
    parsed = [_start_entries(item) for item in found] if isinstance(found, list) and found else []
    entries = [entry for group in parsed if group for entry in group]
    if not entries or any(group is None for group in parsed):
        raise _RefusalError(
            400,
            {
                "error": "until needs a non-empty list of event subjects an alert or a deploy emits, as in "
                "`--until starpulse.trantor.deploy.web.applied`; a task wakes on events only, so a data condition "
                "(a prom query, a date) needs an alert rule that emits one; to wait on a task use "
                "`--until-task TASK-N`, and use `--operator` only for a question the operator must answer"
            },
        )
    if open_ := [name for name in current["dependencies"] if not feed.is_done(name)]:
        raise _RefusalError(
            409,
            {"error": f"{task} already waits on {', '.join(open_)}; a task is gated by one reason, never both"},
        )
    entries = list({entry["id"]: entry for entry in entries}.values())
    block = "```yaml\n" + yaml.safe_dump({"start_criteria": entries}, sort_keys=False) + "```"
    return {
        "description": section_set(current["description"], "Start Criteria", block),
        **({"dependencies": []} if current["dependencies"] else {}),  # Done dependencies gate nothing
    }


def _waiting_description(current: dict[str, Any]) -> dict[str, Any]:
    """The edit a task makes to its description when it parks on a task: its question is moot and its Start Criteria retire."""
    fenced: list[str] = []

    def hold(found: re.Match[str]) -> str:
        fenced.append(found.group())
        return f"\0{len(fenced) - 1}\0"

    text = section_drop(_FENCE.sub(hold, current["description"]), "Needs attention")
    if re.search(_START_CRITERIA, text):
        text = re.sub(_START_CRITERIA, "## Retired Start Criteria", section_drop(text, "Retired Start Criteria"))
    text = re.sub(r"\0(\d+)\0", lambda found: fenced[int(found.group(1))], text)
    return {"description": text} if text != current["description"].strip() else {}


def _without_question(current: dict[str, Any]) -> dict[str, Any]:
    """The edit that drops a Needs attention task's question when the task parks on the task or event that makes it moot."""
    dropped = section_drop(current["description"], "Needs attention")
    return {"description": dropped} if dropped != current["description"].strip() else {}


def _wait_on_operator(reason: Any) -> str:
    """The request comment that asks the task actor to put the task in front of the operator with `reason` as the question."""
    if not _nonblank(reason):
        raise _RefusalError(400, {"error": "operator needs the reason, in text, that only the operator can clear"})
    return f"{ASK_REQUEST} {reason.strip()}"


def _ask_key(reason: str) -> str:
    """What an ask asks, from its blocker on: the leading account of what happened varies between identical asks."""
    blocker = reason.find("Blocker:")
    return " ".join(reason[blocker:].split()).casefold()


def _without_repeat(reason: str, current: dict[str, Any]) -> dict[str, Any]:
    """The edit a park for the operator makes, refused when the operator already answered the task's standing
    `## Needs attention` ask and this is that ask; the refusal cites the newest answer.

    An unanswered ask is asked again: an In Progress task holding one left the lane unanswered (a redispatch), and
    the re-park returns it there."""
    paragraphs = [p.strip() for p in needs_attention_text(current["description"]).split("\n\n") if p.strip()]
    if not paragraphs or _ask_key(paragraphs[0]) != _ask_key(reason):
        return {}
    if answers := [p for p in paragraphs[1:] if p.startswith("Operator answer")]:
        raise _RefusalError(
            409,
            {"error": f"this ask is already recorded in the task's `## Needs attention` section; act on its answer: {answers[-1]}"},
        )
    return {}


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


_BAD_PARK = {
    "error": 'a park needs exactly one reason: "untilTask" (task ids that must reach Done), "until" (event subjects, '
    'one of which releases the task) or "operator" (text)'
}
_PARK_REASONS = ("untilTask", "until", "operator")


def _park_lane(feed: BoardFeed, reason: str) -> str | None:
    """The lane a park for `reason` asks for: where a task waits on a fact, or on the operator."""
    return feed.roles.attention if reason == "operator" else feed.roles.waiting


def _not_parkable(feed: BoardFeed, task: str, state: str) -> tuple[int, dict[str, str]]:
    """The refusal for a park that does not reach a task in `state`, with the way on for the lane it is in."""
    way = {
        feed.roles.ready: f"; start it first (`starpulse task dispatch {task}`), then park it",
        feed.roles.attention: "; the operator's answer returns it to work",
    }
    return 409, {
        "error": f"only an In Progress task can be parked (one waiting on a task or an event settles in Waiting): "
        f"{task} is {state}{way.get(state, '')}"
    }


def park_task(
    task: str, park: Park, comment: str, who: Who, feed: BoardFeed, read: TaskReader, edit: TaskEditor
) -> tuple[int, dict[str, Any]]:
    """Request that the task actor park the In Progress `task` for the one reason `park` names: the HTTP status and JSON body.

    The reason picks the request and writes its gate and request comment in one edit, and no lane: `untilTask` adds
    dependencies (a `TASK-N#K` entry also records the criterion needed), `until` writes the Start Criteria block and a
    `Wait requested:` comment, and `operator` writes an `Ask requested:` comment holding the question. The task actor
    moves the task to Waiting or Needs attention, and the board's rules judge that move.

    A Review or Needs attention task is parked on a task or an event the same way, as a request. A Ready task waiting
    on tasks and a Waiting task waiting on events are gated by the edit with no request, and the park itself moves a
    Ready one to Waiting. A wait on one criterion parks In Progress work only, and an ask the task already records
    with an operator answer is refused.
    """
    reasons = [key for key in _PARK_REASONS if key in park.model_fields_set]
    if len(reasons) != 1:
        return 400, _BAD_PARK
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    reason, roles = reasons[0], feed.roles
    state, value = agent["state"], getattr(park, reasons[0])
    settles = (roles.ready, roles.review, roles.waiting)
    parkable = {
        "untilTask": (roles.working, roles.attention, *settles),
        "until": (roles.working, roles.attention, roles.review, roles.waiting),
        "operator": (roles.working,),
    }[reason]
    if state not in parkable:
        return _not_parkable(feed, task, state)
    if reason == "untilTask" and state != roles.working and (crit := [n for n in value if "#" in str(n)]):
        return 409, {"error": f"a criterion wait ({crit[0]}) parks In Progress work only; wait on the whole task"}
    column = _park_lane(feed, reason)
    if column is None:
        return 409, {"error": f"this board's machine has no lane to park {task} in for {reason}"}
    requested = state in (roles.working, roles.attention, roles.review)
    try:
        asked = {
            "untilTask": lambda: comment,
            "until": lambda: f"{WAIT_REQUEST} {comment or 'its start criteria'}" if requested else comment,
            "operator": lambda: _wait_on_operator(value),
        }[reason]()
    except _RefusalError as refusal:
        return refusal.answer
    plans = {
        "untilTask": lambda current: _wait_on_tasks(feed, task, current, value) | _waiting_description(current),
        "until": lambda current: _wait_on_events(feed, task, current | _without_question(current), value),
        "operator": lambda current: _without_repeat(value, current),
    }
    return _lifecycle_edit(
        feed, task, column, who, asked, read, edit, plans[reason], moves=state == roles.ready
    )
