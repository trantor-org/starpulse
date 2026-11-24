"""The task records: read, edit, archive, judge, restore, retire and create them."""

import contextlib
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.board.adapters.native_scan import dependencies
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.markdown import ARCHIVE_REQUEST
from starpulse.board.model import post_merge_checks
from starpulse.board.model.seam import (
    AGENT,
    TASK_ACTOR,
    Board,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskReopener,
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
    ReopenRequest,
    RestoreRequest,
    RetiredImportRequest,
    RetireRequest,
    TakeOverRequest,
    VerdictRequest,
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
from starpulse.views.application.commands.moves import move_refusal, started_refusal
from starpulse.views.application.commands.replays import Replays

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    pass

logger = logging.getLogger(__name__)


#: The longest title a create accepts; a title is one line on a card, not a description.
_TITLE_MAX = 300
_REF = "ref:"  # a dependency naming a sibling in the same batch create by its `ref`


#: The verdicts a post-merge check takes, as a request spells them and as the comment records them.
_VERDICTS = {"pass": "PASS", "miss": "MISS"}


def task_record(
    feed: BoardFeed, read: TaskReader, task: str, read_archived: TaskReader
) -> tuple[int, dict[str, Any]]:
    """The full record of `task` from the board's reader: the HTTP status and JSON body.

    The record is keyed by the task's editable fields, which the snapshot's small entry does not carry; the page
    opens it with this and sends it back as the `base` of an edit. Reading is not LAN-limited, like the snapshot. An
    archived task is read through `read_archived`, its body `archived`, so a closed task stays readable.
    """
    held, archived, entered = feed.placement(task)
    if not (held or archived) and not feed.wait_replayed(0) and feed.wait_replayed(REPLAY_WAIT_S):
        held, archived, entered = feed.placement(task)
    archived = not held and archived
    if not held and not archived:
        return not_held(feed, task)
    reader = read_archived if archived else read
    if (record := reader(task)) is None:
        return 404, {"error": f"{task} has no record to read"}
    return 200, {"task": task, "record": record, "archived": archived, "entered": entered if archived else None, "done": feed.roles.done}


_REPLAYS = Replays()

#: The edit change that adds a line to the task's notes rather than setting a record field.
_APPEND_NOTES = "appendNotes"
#: The edit change that says why the plan is rewritten, recorded with the `PlanRevised` Event; it is no record field either.
_PLAN_REASON = "planReason"


@with_request(EditRequest, "Editing a task")
def edit_task(
    request: EditRequest, feed: BoardFeed, read: TaskReader, edit: TaskEditor, *, started: Callable[[str], bool]
) -> tuple[int, dict[str, Any]]:
    """Apply the edit `request` names to a task through `edit` in one write: the HTTP status and JSON body.

    A `request_key` that an earlier send of the edit carried answers that send's answer and writes nothing, so a
    client that timed out sends the same key again without appending its comment a second time.
    """
    return _REPLAYS.run(request.request_key, lambda: _edited(request, feed, read, edit, started=started))


def _edited(
    request: EditRequest, feed: BoardFeed, read: TaskReader, edit: TaskEditor, *, started: Callable[[str], bool]
) -> tuple[int, dict[str, Any]]:
    """One edit, as `edit_task` runs it.

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
    if lane != agent["state"] and (refused := started_refusal(feed, task, lane, started) or move_refusal(agent, task, lane, who) or holder_refusal(feed, agent, task, who)) is not None:
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
        if stale := [field for field in fields if current[field] != base[field]]:
            return 409, {
                "error": f"{task} changed since it was opened: {', '.join(stale)}",
                "stale": stale,
                "current": {field: current[field] for field in stale},
            }
        todo = {field: value for field, value in fields.items() if value != current[field]}
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
    return 200, {"task": task, "changed": list(dict.fromkeys(changed))}


@with_request(ArchiveRequest, "Archiving a task")
def archive_task(
    request: ArchiveRequest, feed: BoardFeed, archive: TaskArchiver, edit: TaskEditor
) -> tuple[int, dict[str, Any]]:
    """Archive the task `request` names, or each of its `tasks`, from whichever column it is in, through `archive`: the
    HTTP status and JSON body. A batch answers 200 with the tasks archived and each refused one's error, so one refusal
    leaves the others archived.

    A non-empty `reason` is the writer's to record on the task. The card leaves its column when the board adapter
    next reports the task archived, not on this answer. An agent's archive of an open task is a request: it records an
    `Archive requested:` comment through `edit` and the task actor archives on it.
    """
    reason, who = request.reason or "", who_of(request)
    if request.task is not None:
        return _archive_one(feed, archive, edit, request.task, reason, who)
    archived, refused = [], {}
    for task in request.tasks or ():
        status, body = _archive_one(feed, archive, edit, task, reason, who)
        if status == 200:
            archived.append(task)
        else:
            refused[task] = body["error"]
    return 200, {"archived": archived, "refused": refused}


def _archive_one(
    feed: BoardFeed, archive: TaskArchiver, edit: TaskEditor, task: str, reason: str, who: Who
) -> tuple[int, dict[str, Any]]:
    """Archive one `task` for `archive_task`: the HTTP status and JSON body a single-task request answers."""
    if (agent := held_task(feed, task)) is None:
        if feed.is_archived(task):
            return 200, {"task": task}  # a retry of a write that applied
        return not_held(feed, task)
    if who.actor == AGENT and agent["state"] != feed.roles.done:
        written = record_written(
            feed, task, who, lambda: edit(task, {}, f"{ARCHIVE_REQUEST} {reason.strip()}".strip(), actor=who.actor)
        )
    else:
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


@with_request(VerdictRequest, "Recording a verdict")
def record_verdict(
    request: VerdictRequest, feed: BoardFeed, read: TaskReader, edit: TaskEditor
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
    read: TaskReader,
    edit: TaskEditor,
    archive: TaskArchiver,
    create: TaskCreator,
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
            undone = archive(
                body["task"], f"the MISS verdict on {task} {check} was refused: {written.output}", actor=who.actor
            )
            if not undone.ok:
                error = f"{written.output}; fix {body['task']} was filed and could not be archived: {undone.output}"
                return 409, {"error": error, "skill": written.skill}
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "check": check, "verdict": "MISS", "fix": body["task"]}


@with_request(CompleteRequest, "Completing a task")
def complete_task(
    request: CompleteRequest, feed: BoardFeed, complete: TaskCompleter
) -> tuple[int, dict[str, Any]]:
    """Complete the Done task `request` names through `complete`: the HTTP status and JSON body.

    The board's writer refuses a task that is not Done, which answers 409 with the writer's reason and skill.
    """
    task = request.task
    if held_task(feed, task) is None:
        return not_held(feed, task)
    written = complete(task)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


@with_request(RestoreRequest, "Restoring a task")
def restore_task(request: RestoreRequest, feed: BoardFeed, restore: TaskRestorer) -> tuple[int, dict[str, Any]]:
    """Return the archived task `request` names to the board's tasks through `restore`: the HTTP status and JSON body.

    The restore places the task in a lane, so its writer is noted on the feed as any other move's is. The writer owns
    every other refusal (no archived file, the number already open, the name taken), which answers 409 with its reason.
    """
    task, who = request.task, who_of(request)
    written = record_written(feed, task, who, lambda: restore(task))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


@with_request(ReopenRequest, "Reopening a task")
def reopen_task(
    request: ReopenRequest, feed: BoardFeed, reopen: TaskReopener, landed: Callable[[str], bool]
) -> tuple[int, dict[str, Any]]:
    """Return the Done task `request` names to In Progress through `reopen`: the HTTP status and JSON body.

    A completed task reads as archived, so the feed holds no row `held_task` would pass; the writer owns every refusal
    (not Done, the name taken) and `landed` says whether a merged pull request cites the task, which is refused too:
    its work shipped, so a reopen would deliver it twice. Each refusal answers 409 with its reason. A session's reopen is the task actor's, as a claim's.
    """
    task, who = request.task, who_of(request)
    if landed(task):
        return 409, {"error": f"{task} has a merged pull request: its work shipped"}
    who = who._replace(actor=TASK_ACTOR) if who.actor == AGENT else who
    written = record_written(feed, task, who, lambda: reopen(task, request.reason, actor=who.actor))
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
def retire_task(request: RetireRequest, board: Board) -> tuple[int, dict[str, Any]]:
    """Take the finished task `request` names off the board into its history store through the board's `retire`: the
    HTTP status and JSON body.

    The writer owns every other refusal (an open or unknown task, the number kept with other text, a board not started),
    which answers 409 with its reason.
    """
    task = request.task
    written = board.retire(task)
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


@with_request(RetiredImportRequest, "Importing a retired task")
def import_retired(request: RetiredImportRequest, board: Board) -> tuple[int, dict[str, Any]]:
    """Keep the retired task file `request` holds, {name, text}, in the board's history store through its
    `import_retired`: the HTTP status and JSON body, which holds the task's id. The same file again is accepted; the
    writer's refusal (no id, a task on the board, other text under the kept number) answers 409."""
    name, text = request.name, request.text
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
    spec: CreateSpec, who: Who, create: TaskCreator, feed: BoardFeed | None, siblings: Mapping[str, str]
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
    written = record_written(
        feed, None, who, lambda: create(title, {**details, "created_by": who.created_by}, actor=who.actor)
    )
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
    refusal leaves the others created; a spec naming a `ref:<label>` dependency on an earlier spec's `ref` gets that
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
        status, body = _create(spec, who, create, feed, siblings)
        if status == 201 and spec.ref:
            siblings[spec.ref] = body["task"]
        results.append(body)
    return 200, {"results": results}
