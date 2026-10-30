"""The task records: read, edit, archive, rate, judge, restore, retire and create them."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model import post_merge_checks
from starpulse.board.model.seam import (
    Board,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskRestorer,
)
from starpulse.contracts.api.dto.requests import (
    CREATE_LISTS,
    CREATE_TEXT,
    ArchiveRequest,
    CompleteRequest,
    CreateRequest,
    CreateSpec,
    EditRequest,
    MissRequest,
    RatingRequest,
    RestoreRequest,
    RetiredImportRequest,
    RetireRequest,
    TakeOverRequest,
    VerdictRequest,
)
from starpulse.event_log import rating_events
from starpulse.views.application.commands.guard import (
    EDIT_LOCK,
    Who,
    held_task,
    not_held,
    record_written,
    who_of,
    with_request,
)

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


#: The longest title a create accepts; a title is one line on a card, not a description.
_TITLE_MAX = 300
_REF = "ref:"  # a dependency naming a sibling in the same batch create by its `ref`


#: The verdicts a post-merge check takes, as a request spells them and as the comment records them.
_VERDICTS = {"pass": "PASS", "miss": "MISS"}


def task_record(feed: BoardFeed, read: TaskReader | None, task: str) -> tuple[int, dict[str, Any]]:
    """The full record of `task` from the board's reader: the HTTP status and JSON body.

    The record is keyed by the task's editable fields, which the snapshot's small entry does not carry; the page
    opens it with this and sends it back as the `base` of an edit. Reading is not LAN-limited, like the snapshot.
    """
    if read is None:
        return 404, {"error": "this board cannot read a task's full record"}
    if held_task(feed, task) is None:
        return not_held(feed, task)
    if (record := read(task)) is None:
        return 404, {"error": f"{task} has no record to read"}
    return 200, {"task": task, "record": record}


#: The edit change that adds a line to the task's notes rather than setting a record field.
_APPEND_NOTES = "appendNotes"


@with_request(EditRequest, "Editing a task")
def edit_task(
    request: EditRequest, feed: BoardFeed, read: TaskReader | None, edit: TaskEditor | None
) -> tuple[int, dict[str, Any]]:
    """Apply the edit `request` names to a task through `edit` in one write: the HTTP status and JSON body.

    `base` holds the value each changed field had when the page read the task. The edit is refused 409 when any
    changed field's current value differs, naming those fields with their current values, so another writer's
    change is never overwritten; fields the edit does not touch may differ. The writer refuses a whole edit or
    writes all of it, and its refusal carries the skill that satisfies it. `changes` may also hold `appendNotes`, text
    added to the end of the notes as they are when the write lands: it needs no base and is reported as `notes`. A
    non-blank `comment` is written even when every change already holds, which reports no changed field: a client
    that can only name a field to comment on sends the one it leaves as it is.
    """
    task, base, changes, comment = request.task, request.base, request.changes, request.comment or ""
    if not changes:
        return 400, {
            "error": 'an edit needs {"task": "TASK-N", "base": {...}, "changes": {...}, "comment": "<optional>"}'
        }
    who = who_of(request)
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if held_task(feed, task) is None:
        return not_held(feed, task)
    with EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        # `appendNotes` is no record field: it adds to the notes as they are now, so it has no base to go stale
        fields = {field: value for field, value in changes.items() if field != _APPEND_NOTES}
        for field in fields:
            if field not in current:
                return 400, {"error": f"{field} is not an editable field of {task}"}
            if field not in base:
                return 400, {"error": f"the edit has no base for {field}"}
        if stale := [field for field in fields if current[field] != base[field]]:
            return 409, {
                "error": f"{task} changed since it was opened: {', '.join(stale)}",
                "stale": stale,
                "current": {field: current[field] for field in stale},
            }
        todo = {field: value for field, value in fields.items() if value != current[field]}
        if _APPEND_NOTES in changes:
            todo[_APPEND_NOTES] = changes[_APPEND_NOTES]
        if not todo and not comment.strip():
            return 200, {"task": task, "changed": []}
        from starpulse.board.adapters.task_history import break_glass  # noqa: PLC0415 - the database stack loads when a store does

        with break_glass() if request.break_glass else contextlib.nullcontext():
            written = record_written(feed, task, who, lambda: edit(task, todo, comment, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    changed = ("notes" if field == _APPEND_NOTES else field for field in todo)
    return 200, {"task": task, "changed": list(dict.fromkeys(changed))}


@with_request(ArchiveRequest, "Archiving a task")
def archive_task(request: ArchiveRequest, feed: BoardFeed, archive: TaskArchiver | None) -> tuple[int, dict[str, Any]]:
    """Archive the task `request` names, or each of its `tasks`, from whichever column it is in, through `archive`: the
    HTTP status and JSON body. A batch answers 200 with the tasks archived and each refused one's error, so one refusal
    leaves the others archived.

    A non-empty `reason` is the writer's to record on the task. The card leaves its column when the board adapter
    next reports the task archived, not on this answer.
    """
    if archive is None:
        return 404, {"error": "this board does not archive tasks"}
    reason, who = request.reason or "", who_of(request)
    if request.task is not None:
        return _archive_one(feed, archive, request.task, reason, who)
    archived, refused = [], {}
    for task in request.tasks or ():
        status, body = _archive_one(feed, archive, task, reason, who)
        if status == 200:
            archived.append(task)
        else:
            refused[task] = body["error"]
    return 200, {"archived": archived, "refused": refused}


def _archive_one(
    feed: BoardFeed, archive: TaskArchiver, task: str, reason: str, who: Who
) -> tuple[int, dict[str, Any]]:
    """Archive one `task` for `archive_task`: the HTTP status and JSON body a single-task request answers."""
    if held_task(feed, task) is None:
        return not_held(feed, task)
    written = record_written(feed, task, who, lambda: archive(task, reason, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def _unjudged(task: str, current: Mapping[str, Any], check: str) -> str | None:
    """Why `check` of `task` takes no verdict now, or None when it does: the block is malformed, the task declares no
    such check, or a verdict is already commented, which is final."""
    try:
        declared = post_merge_checks.parse(current["description"])
    except ValueError as error:
        return f"{task}: {error}"
    if not any(declared_check["id"] == check for declared_check in declared or ()):
        return f"{task} declares no post-merge check '{check}'"
    existing = post_merge_checks.verdict_of([comment["text"] for comment in current["comments"]], check)
    if existing is not None:
        return f"{task} check '{check}' already has a {existing} verdict; a verdict is final"
    return None


def _unnamed(request: VerdictRequest | MissRequest) -> bool:
    """Whether a verdict or miss request leaves its task or check blank."""
    return not (request.task.strip() and request.check.strip())


@with_request(RatingRequest, "Recording a rating")
def record_rating(request: RatingRequest, feed: BoardFeed) -> tuple[int, dict[str, Any]]:
    """Record `request`'s change of a task's pass/fail rating as one entry of the `task:ratings` stream, and answer the
    task's rating now with its change count. A change the stream does not take is 503: the control shows
    "Rating not saved.".
    """
    who = who_of(request)
    reason = (request.reason or "").strip()
    fields = rating_events.change(request.task, request.verdict, reason, time.time(), *who)
    rated = feed.rate(fields)
    if rated is None:
        return 503, {"error": "rating not saved"}
    return 200, {
        "task": request.task,
        "verdict": request.verdict,
        "reason": rated["reason"],
        "changes": rated["changes"],
    }


@with_request(VerdictRequest, "Recording a verdict")
def record_verdict(
    request: VerdictRequest, feed: BoardFeed, read: TaskReader | None, edit: TaskEditor | None
) -> tuple[int, dict[str, Any]]:
    """Record the verdict `request` names for a post-merge check of a task as a comment on it, through `edit`: the HTTP
    status and JSON body.

    The check must be declared in the task's `## Post-merge Checks` block and not yet judged: a verdict is final, so a
    second is refused 409 with the malformed block and the undeclared check. A `miss` names the `fix` task already
    filed for it (404 when the feed holds none); `/api/miss` files that fix and records the verdict in one call.
    """
    task, check, verdict, fix = request.task, request.check, request.verdict, request.fix
    if _unnamed(request) or verdict not in _VERDICTS:
        return 400, {"error": 'a verdict needs {"task", "check", "verdict": "pass"|"miss"[, "evidence", "fix"]}'}
    if verdict == "miss" and not fix:
        return 400, {"error": "a miss verdict names the task filed to fix it: add its id as fix"}
    evidence, who = request.evidence or "", who_of(request)
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if held_task(feed, task) is None:
        return not_held(feed, task)
    if verdict == "miss" and held_task(feed, fix) is None:
        return not_held(feed, fix)
    with EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        if refusal := _unjudged(task, current, check):
            return 409, {"error": refusal}
        comment = post_merge_checks.verdict_comment(check, _VERDICTS[verdict], evidence, fix)
        written = record_written(feed, task, who, lambda: edit(task, {}, comment, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "check": check, "verdict": _VERDICTS[verdict], **({"fix": fix} if fix else {})}


@with_request(MissRequest, "Recording a miss")
def record_miss(
    request: MissRequest,
    feed: BoardFeed,
    read: TaskReader | None,
    edit: TaskEditor | None,
    archive: TaskArchiver | None,
    create: TaskCreator | None,
) -> tuple[int, dict[str, Any]]:
    """File the fix task `request` names for a missed post-merge check and record the MISS verdict naming it, in one
    call: the HTTP status and JSON body, which holds the fix's id.

    The request is `{task, check, fix: {title, ...as a create}[, evidence]}`. Both writes or neither: a fix whose
    verdict comment is refused is archived again, so a refused miss leaves no fix task and no verdict. A board that
    cannot archive is refused 404, since the fix could not be undone.
    """
    if _unnamed(request):
        return 400, {"error": 'a miss needs {"task", "check", "fix": {"title", ...}[, "evidence"]}'}
    task, check, evidence, who = request.task, request.check, request.evidence or "", who_of(request)
    if read is None or edit is None or archive is None or create is None:
        return 404, {"error": "this board does not edit, archive and create tasks"}
    if held_task(feed, task) is None:
        return not_held(feed, task)
    with EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        if refusal := _unjudged(task, current, check):
            return 409, {"error": refusal}
        status, body = _create(request.fix, who, create, feed, {})
        if status != 201:
            return status, body
        comment = post_merge_checks.verdict_comment(check, "MISS", evidence, body["task"])
        written = record_written(feed, task, who, lambda: edit(task, {}, comment, actor=who.actor))
        if not written.ok:
            archive(body["task"], f"the MISS verdict on {task} {check} was refused: {written.output}", actor=who.actor)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "check": check, "verdict": "MISS", "fix": body["task"]}


@with_request(CompleteRequest, "Completing a task")
def complete_task(
    request: CompleteRequest, feed: BoardFeed, complete: TaskCompleter | None
) -> tuple[int, dict[str, Any]]:
    """Complete the Done task `request` names through `complete`: the HTTP status and JSON body.

    The board's writer refuses a task that is not Done, which answers 409 with the writer's reason and skill.
    """
    task = request.task
    if complete is None:
        return 404, {"error": "this board does not complete tasks"}
    if held_task(feed, task) is None:
        return not_held(feed, task)
    written = complete(task)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


@with_request(RestoreRequest, "Restoring a task")
def restore_task(request: RestoreRequest, feed: BoardFeed, restore: TaskRestorer | None) -> tuple[int, dict[str, Any]]:
    """Return the archived task `request` names to the board's tasks through `restore`: the HTTP status and JSON body.

    The restore places the task in a lane, so its writer is noted on the feed as any other move's is. The writer owns
    every other refusal (no archived file, the number already open, the name taken), which answers 409 with its reason.
    """
    task, who = request.task, who_of(request)
    if restore is None:
        return 404, {"error": "this board does not restore tasks"}
    written = record_written(feed, task, who, lambda: restore(task))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


@with_request(TakeOverRequest, "Taking a task over")
def take_over_task(
    request: TakeOverRequest, take_over: Callable[[str], bool] | None, feed: BoardFeed
) -> tuple[int, dict[str, Any]]:
    """Flip the unattended task `request` names to interactive through `take_over`: the HTTP status and JSON body.

    The Update carries no payload; the workflow only stops typing into the task's pane. A task with no workflow (an
    attended one) answers 409. An accepted take-over shows as interactive in the feed's snapshots.
    """
    task = request.task
    if take_over is None:
        return 404, {"error": "this instance runs no task workflows"}
    if not take_over(task):
        return 409, {"error": f"{task} has no running workflow to take over"}
    feed.record_take_over(task)
    return 200, {"task": task}


@with_request(RetireRequest, "Retiring a task")
def retire_task(request: RetireRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Take the finished task `request` names off the board into its history store through the board's `retire`: the
    HTTP status and JSON body.

    The writer owns every other refusal (an open or unknown task, the number kept with other text, a board not started),
    which answers 409 with its reason.
    """
    task = request.task
    if board is None or board.retire is None:
        return 404, {"error": "this board does not retire tasks"}
    written = board.retire(task)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def retired_list(board: Board | None, task: str, milestone: str = "") -> tuple[int, dict[str, Any]]:
    """The retired task `task` names, or every retired task for a blank one, each {task, name, text}, only those of
    `milestone` when it is not blank: the HTTP status and JSON body. Reading is not LAN-limited."""
    if board is None or board.retired is None:
        return 404, {"error": "this board keeps no retired tasks"}
    return 200, {"tasks": board.retired(task, milestone)}


@with_request(RetiredImportRequest, "Importing a retired task")
def import_retired(request: RetiredImportRequest, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Keep the retired task file `request` holds, {name, text}, in the board's history store through its
    `import_retired`: the HTTP status and JSON body, which holds the task's id. The same file again is accepted; the
    writer's refusal (no id, a task on the board, other text under the kept number) answers 409."""
    name, text = request.name, request.text
    if board is None or board.import_retired is None:
        return 404, {"error": "this board does not import retired tasks"}
    written = board.import_retired(name, text)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": written.output}


def _create_details(request: CreateSpec) -> dict[str, Any]:
    """The filled details of a create, as the board's writer takes them."""
    fields = {field: getattr(request, field) for field in (*CREATE_TEXT, *CREATE_LISTS)}
    details = {field: value for field, value in fields.items() if value}
    if "definitionOfDone" in details:
        details["definitionOfDone"] = [{"text": item, "checked": False} for item in details["definitionOfDone"]]
    return details


def _create(
    spec: CreateSpec, who: Who, create: TaskCreator | None, feed: BoardFeed | None, siblings: Mapping[str, str]
) -> tuple[int, dict[str, Any]]:
    """Create the task `spec` names through `create`, in the lane its `status` names or else the board's starting
    lane, with each `ref:<label>` dependency replaced by the id `siblings` holds for the label."""
    title = (spec.title or "").strip()
    if not title or len(title) > _TITLE_MAX:
        return 400, {"error": f'a create needs {{"title": "<1 to {_TITLE_MAX} characters>"}}'}
    if create is None:
        return 404, {"error": "this board does not create tasks"}
    details = _create_details(spec)
    if "dependencies" in details:
        dependencies = [
            siblings.get(item[len(_REF) :], item) if item.startswith(_REF) else item for item in details["dependencies"]
        ]
        if unresolved := [item for item in dependencies if item.startswith(_REF)]:
            return 409, {"error": f"depends on {', '.join(unresolved)}, which no earlier task in the batch created"}
        details["dependencies"] = dependencies
    # the id is the writer's to choose, so the lane is recorded under the id the write returns
    written = record_written(
        feed, None, who, lambda: create(title, {**details, "created_by": who.created_by}, actor=who.actor)
    )
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 201, {"task": written.output}


@with_request(CreateRequest, "Creating a task")
def create_task(
    request: CreateRequest, create: TaskCreator | None, feed: BoardFeed | None = None
) -> tuple[int, dict[str, Any]]:
    """Create the task `request` names, or each of its `tasks`: the HTTP status and JSON body, which holds the new
    task's id.

    A batch answers 200 with a result per spec, in order: the new `task` id or the `error` that refused it. One
    refusal leaves the others created; a spec naming a `ref:<label>` dependency on an earlier spec's `ref` gets that
    spec's new id, and is refused when that spec was.

    The card appears in its column when the board adapter next reports the task, not on this answer.
    """
    who = who_of(request)
    if request.tasks is None:
        return _create(request, who, create, feed, {})
    siblings: dict[str, str] = {}
    results = []
    for spec in request.tasks:
        status, body = _create(spec, who, create, feed, siblings)
        if status == 201 and spec.ref:
            siblings[spec.ref] = body["task"]
        results.append(body)
    return 200, {"results": results}
