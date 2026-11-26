"""The task records: read, edit, archive, restore, retire and create them."""

import contextlib
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError

from starpulse.board.adapters.native_scan import dependencies
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.markdown import ARCHIVE_REQUEST, FREEZE_REQUEST, MOVE_REQUEST, REQUESTED_BY, UNFREEZE_REQUEST
from starpulse.board.model.seam import (
    AGENT,
    OPERATOR,
    TASK_ACTOR,
    Board,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskReopener,
    TaskRestorer,
    TaskRetirer,
)
from starpulse.contracts.api.dto.requests import (
    CREATE_LISTS,
    CREATE_TEXT,
    CreateRequest,
    CreateSpec,
    EditRequest,
    TaskDeleteRequest,
    TaskPutRequest,
)
from starpulse.machine_engine.model.transitions import lane_id
from starpulse.views.application.commands.guard import (
    EDIT_LOCK,
    REPLAY_WAIT_S,
    Who,
    held_task,
    holder_refusal,
    not_held,
    record_written,
    who_of,
    with_request,
)
from starpulse.views.application.commands.lifecycle import park_task
from starpulse.views.application.commands.moves import (
    Dispatcher,
    Entrypoint,
    Live,
    dispatch_task,
    move_refusal,
    remote_control_refusal,
    started_refusal,
)
from starpulse.views.application.commands.replays import Replays

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


#: The longest title a create accepts; a title is one line on a card, not a description.
_TITLE_MAX = 300
_REF = "ref:"  # a dependency naming a sibling in the same batch create by its `ref`


def task_record(
    feed: BoardFeed, read: TaskReader, task: str, read_archived: TaskReader
) -> tuple[int, dict[str, Any]]:
    """The full record of `task` from the board's reader: the HTTP status and JSON body.

    The record is keyed by the task's editable fields, which the snapshot's small entry does not carry; the page
    opens it with this and sends it back as the `base` of an edit. Reading is not LAN-limited, like the snapshot. An
    archived task is read through `read_archived`, its body `archived`, so a closed task stays readable. An alias
    answers with the task that carries it, never an archived ghost bearing the alias as its id.
    """
    task = feed.current_id(task)
    held, archived, entered = feed.placement(task)
    if not (held or archived) and not feed.wait_replayed(0) and feed.wait_replayed(REPLAY_WAIT_S):
        feed.repin()
        held, archived, entered = feed.placement(task)
    archived = not held and archived
    if not held and not archived:
        return not_held(feed, task)
    reader = read_archived if archived else read
    if (record := reader(task)) is None:
        return 404, {"error": f"{task} has no record to read"}
    return 200, {"id": record.get("uuid") or "", "key": task, "task": task, "record": record, "archived": archived, "entered": entered if archived else None, "done": feed.roles.done}


_REPLAYS = Replays()

#: The edit change that adds a line to the task's notes rather than setting a record field.
_APPEND_NOTES = "appendNotes"
#: The edit change that says why the plan is rewritten, recorded with the `PlanRevised` Event; it is no record field either.
_PLAN_REASON = "planReason"


def _spelled(field: str, value: Any) -> Any:
    """`value` as the edit compares it: a status is its lane, however the page or the board spells it."""
    return lane_id(value) if field == "status" and isinstance(value, str) else value


def _edited(
    request: EditRequest,
    feed: BoardFeed,
    read: TaskReader,
    edit: TaskEditor,
    *,
    started: Callable[[str], bool],
    entrypoint: Entrypoint | None = None,
) -> tuple[int, dict[str, Any]]:
    """One edit, as `put_task` runs it.

    `base` holds the value each changed field had when the page read the task. The edit is refused 409 when any
    changed field's current value differs, naming those fields with their current values, so another writer's
    change is never overwritten; fields the edit does not touch may differ. The writer refuses a whole edit or
    writes all of it, and its refusal carries the skill that satisfies it. `changes` may also hold `appendNotes`, text
    added to the end of the notes as they are when the write lands: it needs no base and is reported as `notes`; and
    `planReason`, why the plan changes, which a plan rewritten after work began needs and which has no base either. A
    non-blank `comment` is written even when every change already holds, which reports no changed field: a client
    that can only name a field to comment on sends the one it leaves as it is.
    """
    task, base, changes, comment = request.task, request.base, request.changes, request.comment or ""
    if not changes and not comment.strip():
        return 400, {
            "error": 'an edit needs {"task": "TASK-N", "base": {...}, "changes": {...}, "comment": "<optional>"}'
        }
    who = who_of(request)
    if (agent := held_task(feed, task)) is None:
        return not_held(feed, task)
    if holder_refusal(feed, agent, task, who) is not None and not comment.strip():
        comment = f"Edited by session {who.session}, not the holder: {', '.join(sorted(changes))}"
    lane = lane_id(str(changes["status"])) if "status" in changes else agent["state"]
    if lane != agent["state"] and (refused := (lane == feed.roles.working and remote_control_refusal(task, who.session, entrypoint)) or started_refusal(feed, task, lane, started) or move_refusal(agent, task, lane, who) or holder_refusal(feed, agent, task, who)) is not None:
        return refused  # a status written beside other fields is a move: the machine offers it to `who` or it is refused
    with EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        # `appendNotes` is no record field: it adds to the notes as they are now, so it has no base to go stale
        fields = {field: value for field, value in changes.items() if field not in (_APPEND_NOTES, _PLAN_REASON)}
        for field in fields:
            if field not in current:
                return 400, {"error": f"{field} is not an editable field of {task}"}
            if field not in base:
                return 400, {"error": f"the edit has no base for {field}"}
        if stale := [field for field in fields if _spelled(field, current[field]) != _spelled(field, base[field])]:
            return 409, {
                "error": f"{task} changed since it was opened: {', '.join(stale)}",
                "stale": stale,
                "current": {field: current[field] for field in stale},
            }
        todo = {field: value for field, value in fields.items() if value != current[field]}
        if who.actor == OPERATOR and lane != agent["state"]:  # the task actor makes the operator's move from the request
            todo.pop("status", None)
            comment = f"{MOVE_REQUEST} {lane}. {comment.strip()}".strip()
        if _APPEND_NOTES in changes:
            todo[_APPEND_NOTES] = changes[_APPEND_NOTES]
        if _PLAN_REASON in changes and "plan" in todo:
            todo[_PLAN_REASON] = changes[_PLAN_REASON]
        if not todo and not comment.strip():
            return 200, {"task": task, "changed": []}
        from starpulse.board.adapters.task_history import break_glass  # noqa: PLC0415 - the database stack loads when a store does

        with break_glass() if request.break_glass else contextlib.nullcontext():
            written = record_written(feed, task, who, lambda: edit(task, todo, comment, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    changed = ("notes" if field == _APPEND_NOTES else field for field in todo if field != _PLAN_REASON)
    return 200, {
        "task": task,
        "changed": list(dict.fromkeys(changed)),
        **({"advice": written.advice} if written.advice else {}),
        **({"warnings": list(written.warnings)} if written.warnings else {}),
    }


def _archive_one(
    feed: BoardFeed, archive: TaskArchiver, edit: TaskEditor, task: str, reason: str, who: Who
) -> tuple[int, dict[str, Any]]:
    """Archive one `task` for `delete_task`: the HTTP status and JSON body it answers."""
    if (agent := held_task(feed, task)) is None:
        if feed.is_archived(task):
            return 200, {"task": task, "requested": False}  # a retry of a write that applied
        return not_held(feed, task)
    requested = who.actor == AGENT and agent["state"] != feed.roles.done
    if requested:
        written = record_written(
            feed, task, who, lambda: edit(task, {}, f"{ARCHIVE_REQUEST} {reason.strip()}".strip(), actor=who.actor)
        )
    else:
        written = record_written(feed, task, who, lambda: archive(task, reason, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "requested": requested}


def _completed(task: str, feed: BoardFeed, complete: TaskCompleter) -> tuple[int, dict[str, Any]]:
    if held_task(feed, task) is None:
        return not_held(feed, task)
    written = complete(task)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def _freeze_requested(
    task: str, request: TaskPutRequest, who: Who, feed: BoardFeed, edit: TaskEditor
) -> tuple[int, dict[str, Any]]:
    """Record a request that the task actor freeze `task`, or lift its freeze: the actor alone writes `frozen`."""
    if held_task(feed, task) is None:
        return not_held(feed, task)
    freezing = request.freeze is not None
    first = f"{FREEZE_REQUEST} {request.freeze}" if freezing else UNFREEZE_REQUEST
    by = OPERATOR if who.actor == OPERATOR else who.created_by
    comment = f"{first}\n{REQUESTED_BY} {by}"
    written = record_written(feed, task, who, lambda: edit(task, {}, comment, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "request": "freeze" if freezing else "unfreeze"}


def _restored(task: str, who: Who, feed: BoardFeed, restore: TaskRestorer) -> tuple[int, dict[str, Any]]:
    written = record_written(feed, task, who, lambda: restore(task))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def _dispatched(
    task: str,
    request: TaskPutRequest,
    feed: BoardFeed,
    dispatch: Dispatcher | None,
    entrypoint: Entrypoint | None,
    live: Live | None,
) -> tuple[int, dict[str, Any]]:
    """The dispatch an `assignee` change names: it stands alone, and names the session to pin."""
    session = request.changes["assignee"]
    if set(request.changes) != {"assignee"} or not isinstance(session, str) or not session.strip():
        return 400, {"error": "a dispatch changes only `assignee`, to the session to pin"}
    replaces = request.base.get("assignee")
    return dispatch_task(task, session, replaces if isinstance(replaces, str) else "", feed, dispatch, entrypoint, live)


def _reopened(
    task: str,
    reason: str,
    who: Who,
    feed: BoardFeed,
    reopen: TaskReopener,
    landed: Callable[[str], bool],
    opened: Callable[[str], bool],
) -> tuple[int, dict[str, Any]]:
    if landed(task):
        return 409, {"error": f"{task} has a merged pull request: its work shipped"}
    who = who._replace(actor=TASK_ACTOR) if who.actor == AGENT else who
    written = record_written(feed, task, who, lambda: reopen(task, reason, actor=who.actor, ready=opened(task)))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def _taken_over(task: str, take_over: Callable[[str], bool] | None, feed: BoardFeed) -> tuple[int, dict[str, Any]]:
    if take_over is None:
        return 404, {"error": "this instance runs no task workflows"}
    if not take_over(task):
        return 409, {"error": f"{task} has no running workflow to take over"}
    feed.record_take_over(task)
    return 200, {"task": task}


def _retired(task: str, retire: TaskRetirer) -> tuple[int, dict[str, Any]]:
    written = retire(task)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def retired_list(board: Board, task: str, milestone: str = "", fields: str = "") -> tuple[int, dict[str, Any]]:
    """The retired task `task` names, or every retired task for a blank one, each {task, name, text}, only those of
    `milestone` when it is not blank: the HTTP status and JSON body, whose `tasks` for a blank `task` may be an iterator
    reading a page of rows at a time. `fields=dependencies` answers each as {task, dependencies} alone, the ids its
    file lists. Reading is not LAN-limited."""
    if fields not in ("", "dependencies"):
        return 400, {"error": f"fields {fields!r} is not a retired projection; use dependencies"}
    if not fields:
        return 200, {"tasks": board.retired(task, milestone)}
    edges = board.retired_projected(dependencies, task, milestone)
    return 200, {"tasks": [{"task": id_, "dependencies": found} for id_, found in edges]}


#: How many retired tasks `GET /api/retired` answers when `?limit=` is absent, and the most it answers at once.
RETIRED_PAGE = 200
RETIRED_PAGE_LIMIT = 500


def retired_page(board: Board, limit: str, before: str) -> tuple[int, dict[str, Any]]:
    """One page of the retired tasks, newest retired first, each {task, name, text}: at most `limit` (default
    `RETIRED_PAGE`, the text of a query) after the cursor `before`, and `next`, the cursor of the page that follows,
    when there is one: the HTTP status and JSON body. A limit or cursor that is malformed is 400."""
    try:
        size = int(limit) if limit else RETIRED_PAGE
        if not 0 < size <= RETIRED_PAGE_LIMIT:
            raise ValueError(limit)
        rows, following = board.retired_page(size, before)
    except ValueError:
        return 400, {"error": f"retired takes a ?limit= from 1 to {RETIRED_PAGE_LIMIT} and the ?before= of a previous page's next"}
    return 200, {"tasks": rows, "next": following}


def _create_details(request: CreateSpec) -> dict[str, Any]:
    """The filled details of a create, as the board's writer takes them."""
    fields = {field: getattr(request, field) for field in (*CREATE_TEXT, *CREATE_LISTS)}
    details = {field: value for field, value in fields.items() if value}
    if request.members:
        details["members"] = request.members
    if "definitionOfDone" in details:
        details["definitionOfDone"] = [{"text": item, "checked": False} for item in details["definitionOfDone"]]
    return details


def _create(
    spec: CreateSpec,
    who: Who,
    create: TaskCreator,
    feed: BoardFeed | None,
    siblings: Mapping[str, str],
    cohort: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Create the task `spec` names through `create`, in the lane its `status` names or else the board's starting
    lane, with each `ref:<label>` dependency replaced by the id `siblings` holds for the label."""
    title = (spec.title or "").strip()
    if not title or len(title) > _TITLE_MAX:
        return 400, {"error": f'a create needs {{"title": "<1 to {_TITLE_MAX} characters>"}}'}
    details = _create_details(spec)
    if "dependencies" in details:
        dependencies = [
            siblings.get(item[len(_REF) :], item) if item.startswith(_REF) else item for item in details["dependencies"]
        ]
        if unresolved := [item for item in dependencies if item.startswith(_REF)]:
            return 409, {"error": f"depends on {', '.join(unresolved)}, which no earlier task in the batch created"}
        details["dependencies"] = dependencies
    # the id is the writer's to choose, so the lane is recorded under the id the write returns
    extra = {"cohort": True} if cohort else {}
    try:
        written = record_written(
            feed, None, who, lambda: create(title, {**details, "created_by": who.created_by}, actor=who.actor, **extra)
        )
    except OperationalError as error:
        if "database is locked" not in str(error):
            raise
        return 503, {"error": "the database is locked; send the create again"}
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 201, {"task": written.output}


@with_request(CreateRequest, "Creating a task")
def create_task(
    request: CreateRequest, create: TaskCreator, feed: BoardFeed | None = None
) -> tuple[int, dict[str, Any]]:
    """Create the task `request` names, or each of its `tasks`: the HTTP status and JSON body, which holds the new
    task's id.

    A batch answers 200 with a result per spec, in order: the new `task` id or the `error` that refused it. One
    refusal leaves the others created; a board set to `cohort_milestone` refuses each spec with no `milestone` in a batch
    of two or more; a spec naming a `ref:<label>` dependency on an earlier spec's `ref` gets that
    spec's new id, and is refused when that spec was.

    A `request_key` that an earlier send of the create carried answers that send's answer and files nothing, so a
    client that timed out sends the same key again without filing a second task.

    The card appears in its column when the board adapter next reports the task, not on this answer.
    """
    return _REPLAYS.run(request.request_key, lambda: _created(request, create, feed))


def _created(request: CreateRequest, create: TaskCreator, feed: BoardFeed | None) -> tuple[int, dict[str, Any]]:
    who = who_of(request)
    if request.tasks is None:
        return _create(request, who, create, feed, {})
    siblings: dict[str, str] = {}
    results = []
    for spec in request.tasks:
        status, body = _create(spec, who, create, feed, siblings, cohort=len(request.tasks) > 1)
        if status == 201 and spec.ref:
            siblings[spec.ref] = body["task"]
        results.append(body)
    return 200, {"results": results}


@with_request(TaskPutRequest, "Writing a task")
def put_task(
    request: TaskPutRequest,
    task: str,
    feed: BoardFeed,
    board: Board,
    take_over: Callable[[str], bool] | None,
    landed: Callable[[str], bool],
    *,
    started: Callable[[str], bool],
    opened: Callable[[str], bool] = lambda _: False,
    dispatch: Dispatcher | None = None,
    entrypoint: Entrypoint | None = None,
    live: Live | None = None,
) -> tuple[int, dict[str, Any]]:
    """Write `task` as `PUT /api/tasks/{id}` says: the HTTP status and JSON body of the verb the body names.

    `reopen` reopens the Done task, into Ready when an `opened` pull request cites it, else In Progress;
    `completed: true` completes it, `archived: false` restores it, `retired: true` retires the finished task, which
    the board's writer refuses (409, with its reason) while it is open, `interactive: true` takes it over, `park`
    parks it and `freeze` or `unfreeze` records the request the task actor carries out; a change that names only an
    `assignee` dispatches that session to the task, its `base` assignee the holder it replaces; any other body is an
    edit over its `base`.
    """
    who = who_of(request)
    if request.park is not None:
        return park_task(task, request.park, request.comment or "", who, feed, board.read, board.edit)
    if request.freeze is not None or request.unfreeze is not None:
        return _freeze_requested(task, request, who, feed, board.edit)
    if request.reopen is not None:
        return _reopened(task, request.reopen, who, feed, board.reopen, landed, opened)
    if request.completed is not None:
        return _completed(task, feed, board.complete)
    if request.archived is not None:
        return _restored(task, who, feed, board.restore)
    if request.retired is not None:
        return _retired(task, board.retire)
    if request.interactive is not None:
        return _taken_over(task, take_over, feed)
    if "assignee" in request.changes:
        return _dispatched(task, request, feed, dispatch, entrypoint, live)
    edit = EditRequest(
        task=task,
        base=request.base,
        changes=request.changes,
        comment=request.comment,
        breakGlass=request.break_glass,
        request_key=request.request_key,
        actor=request.actor,
        session=request.session,
        harness=request.harness,
    )
    return _REPLAYS.run(request.request_key, lambda: _edited(edit, feed, board.read, board.edit, started=started, entrypoint=entrypoint))


@with_request(TaskDeleteRequest, "Archiving a task")
def delete_task(
    request: TaskDeleteRequest, task: str, feed: BoardFeed, board: Board
) -> tuple[int, dict[str, Any]]:
    """Archive `task` as `DELETE /api/tasks/{id}` says."""
    return _archive_one(feed, board.archive, board.edit, task, request.reason or "", who_of(request))
