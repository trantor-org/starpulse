"""The write routes of StarPulse's HTTP server: each handler takes the request's source, body and the seam it writes through,
and answers the HTTP status and JSON body.

`starpulse._internal.server.server` routes a request here after its write guard (`write_refusal`: 415 for a body that is not JSON, 403 for
another site's origin) and dispatches to these; the read responses, the stream and the assembly stay there. A write
that names a task the feed has not placed waits up to `REPLAY_WAIT_S` for a replay in progress, then answers 503, which
a client sends again, never 404 for a task the replay has yet to reach. Every handler parses its body through the
request model it is declared with (`_write`, `contracts.api.dto.requests`): a body that is not JSON, not an object, or
holds an unnamed key, a field of the wrong type or a blank `actor`, `session` or `harness` answers 400
`invalid request: <field>: <reason>` for its first fault, whatever the route's own "400 for" list names. The routes:

POST /api/run/<instance>/<workflow>
                   start a run-safe workflow through its instance's optional `start`: {runId}, or {error}
                   with 403 for a source outside loopback and RFC 1918, 404 when the instance has no adapter
                   that can start a run or the workflow is not in its `run_safe`, 502 when the adapter's start
                   fails. A GET answers 405
POST /api/runs/<instance>/<workflow>/rerun
                   start a run-safe workflow again, forced, with the commit its newest unresolved failure
                   applied, through its instance's optional `rerun`: {runId}, or {error} with 403 for a source
                   outside loopback and RFC 1918, 404 when the instance has no adapter that can rerun or the
                   workflow is not in its `run_safe`, 409 when the instance declares no force parameter or the
                   workflow has no unresolved failure, 502 when the adapter's rerun fails. A GET answers 405
POST /api/move     {task, to[, actor, session, harness]}: set a Board task's status through the board adapter's writer, as
                   `actor` (the page names `operator`; absent, `agent` with a session, else `anonymous`). An actor outside the event's declared writers
                   is refused 409 before the writer is asked; a board with no writer answers 501
POST /api/claim    {task, session[, actor, harness]}: move a task to In Progress holding `session`, an opaque string; 409
                   when the task is In Progress under another assignee, or `session` already holds another In Progress
                   task, with the writer's or the machine's refusal as for a move; the same session claiming its own
                   task again answers 200. {task, to, assignee}
POST /api/park     {task, untilTask | until | operator[, comment, session, actor, harness]}: park the In Progress
                   task for exactly one typed reason, in one write that picks the lane: `untilTask` (task ids that
                   must reach Done) and `until` (start criteria, each an {id, kind, ...} object) go to Waiting,
                   `operator` (text only the operator can answer) to Needs attention. {task, to}; refusals as for an
                   edit, 409 when the task is not In Progress, a task waited on is itself, unknown or Done, or the task
                   has an open dependency and is given criteria
POST /api/review   {task, references, summary, comment[, session, actor, harness]}: move the task to Review with the
                   pull requests and final summary it ships in the same write, so the configured rules judge the
                   evidence and a refusal writes nothing. {task, to}; refusals as for an edit
GET /api/task/<id> {task, record}: every editable field of a task from the board's `read`, which the snapshot's
                   entry does not carry; 404 when the board cannot read or the task is not on it
POST /api/edit     {task, base, changes, comment[, actor, session, harness]}: one write of every change through the board's `edit`. 409 with the
                   stale fields and their current values when any changed field no longer equals its `base`, or with
                   the writer's refusal and its skill; 403 outside loopback and RFC 1918. A GET answers 405
POST /api/verdict  {task, check, verdict: "pass"|"miss"[, evidence, fix, actor, session, harness]}: comment the verdict of
                   a post-merge check the task's `## Post-merge Checks` block declares, `[post-merge-check] <id> PASS|MISS`
                   with `Fix: <task>` for a miss, through the board's `edit`; 200 {task, check, verdict[, fix]}. 409 for a
                   malformed block, an undeclared check or one already judged (a verdict is final); 404 for a miss whose
                   fix the board does not hold; 400 for a miss without a fix
POST /api/miss     {task, check, fix: {title, ...as a create}[, evidence, actor, session, harness]}: file the fix task and
                   record the MISS verdict naming it in one call, 200 {task, check, verdict, fix}. A verdict refused after
                   the fix is filed archives the fix again, so a refused miss leaves neither; 404 for a board that cannot
                   edit, archive and create
POST /api/archive  {task, reason[, actor, session, harness]}: archive a task from any lane through the board's `archive`; refusals as for
                   an edit
POST /api/complete {task}: move a Done task into the board's completed tasks through its `complete`; refusals
                   as for an edit (409 for a task that is not Done), 404 when the board does not complete or the task is
                   not on it
POST /api/restore  {task[, actor, session, harness]}: return an archived task to the board's tasks, unchanged, through its `restore`; 409 with the
                   writer's refusal for a task that is not archived, is already open or completed, or whose file name is
                   taken, 404 when the board does not restore
POST /api/retire   {task}: take a finished task (Done, completed or archived) off the board into the history store's
                   retired tasks through its `retire`, kept byte-for-byte; 409 with the writer's refusal for an open or
                   unknown task or a number kept with other text, 404 when the board does not retire
GET /api/retired[?task=<id>]
                   {tasks}: the retired tasks, or the one `task` names, each {task, name, text}; 404 for a board that
                   keeps none. A `restore` of a retired task returns its file to the board's tasks
POST /api/retired/import
                   {name, text}: keep a retired task file a client held in the history store through the board's
                   `import_retired`, and answer 200 {task}; the same file again is accepted, 409 for other text under a
                   kept number, a task on the board or a file with no id, 404 when the board does not import
POST /api/tasks    {title, description, priority, impact, urgency, labels, milestone, profile, dependencies, acceptanceCriteria[,
                   actor, session, harness]}: create, stamping `created_by: <harness>:<session>`
                   a task in the board's starting lane through the board's `create`, and answer 201 {task}
                   with its id; only the title is required. 400 for a missing, blank or over-long title or a detail of
                   the wrong kind, 403 outside loopback and RFC 1918, 404 when the board
                   does not create (the snapshot's `capabilities.create` says which). `{tasks: [{title, ..., ref}]}`
                   in place of the title creates each spec and answers 200 {results: [{task} or {error[, skill]}]} in
                   order; one refused spec leaves the others created, and a `ref:<label>` dependency is the new id
                   of the earlier spec with that `ref`. A GET answers 405
GET /api/milestones, /api/milestones/<id>
                   {milestones} or {milestone}: the board's open milestones, each {id, title, outcome, specs, adrs, retro,
                   description}; 404 for a board that keeps none or for a milestone that is not open
POST /api/milestones, /api/milestones/edit, /api/milestones/archive
                   {title[, outcome, specs, adrs, retro]} (201 {milestone}, the new id), {milestone, changes} (200
                   {milestone, changed}) and {milestone} (200 {milestone}), through the board's `create_milestone`,
                   `edit_milestone` and `archive_milestone`; 400 for a malformed body or detail, 403 outside loopback and
                   RFC 1918, 404 for a board without the writer or a milestone that is not open, 409 for the writer's
                   refusal. A GET answers 405
GET /api/docs, /api/docs/<id>
                   {docs} or {doc}: the board's open docs, each {id, title, type, created_date, updated_date, path} and, for one
                   doc, its `body`; 404 for a board that keeps none or for a doc that is not open
POST /api/docs, /api/docs/edit, /api/docs/archive, /api/docs/restore
                   {title[, type, folder, body]} (201 {doc}, the new id), {doc, changes} (200 {doc, changed}), {doc} (200
                   {doc}) and {doc[, folder]} (200 {doc}, the archived file returned unchanged under `docs/<folder>`),
                   through the board's `create_doc`, `edit_doc`, `archive_doc` and `restore_doc`; 400 for a malformed body or
                   detail, 403 outside loopback and RFC 1918, 404 for a board without the writer or a doc that is not open,
                   409 for the writer's refusal. A GET answers 405. These routes read the same Board as the milestone routes
POST /api/start    {task, profile, harness[, mode, actor]}: start a task's session at `session_start_url` on
                   `harness` (`mode` defaults to `interactive`; see Start in the README)
GET /api/scheduler {enabled, sampledAt, dimensions}: whether the scheduler admits tasks, when capacity was last sampled
                   and, for `cpu`, `memory`, `sessions` and `review`, each dimension's {name, use, limit}; no
                   dimensions before the first sample
PUT /api/scheduler {enabled: bool}: switch admission on or off by writing the file the scheduler reads, and answer the
                   status as a GET does; 400 for a body naming none of `enabled`, `harness` and `quietHours` or
                   naming `enabled` as anything but a boolean, 403 outside loopback and RFC 1918
"""

from __future__ import annotations

import contextlib
import functools
import ipaddress
import logging
import re
import threading
import time
from collections.abc import Callable, Collection, Mapping
from typing import TYPE_CHECKING, Any, Concatenate, NamedTuple
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ValidationError

from starpulse.board.model import post_merge_checks
from starpulse.board.model.seam import (
    AGENT,
    ANONYMOUS,
    AssigneeWriter,
    Board,
    MoveWriter,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskRestorer,
    Written,
)
from starpulse._internal.config.harnesses import Harnesses
from starpulse.board.board_feed import BoardFeed
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.contracts.adapters import Move, StartFailedError
from starpulse.contracts.api.dto.requests import (
    CREATE_LISTS,
    CREATE_TEXT,
    ArchiveRequest,
    ClaimRequest,
    CompleteRequest,
    CreateRequest,
    CreateSpec,
    DocArchiveRequest,
    DocCreateRequest,
    DocEditRequest,
    DocRestoreRequest,
    EditRequest,
    MilestoneArchiveRequest,
    MilestoneCreateRequest,
    MilestoneEditRequest,
    MissRequest,
    MoveRequest,
    NonBlank,
    ParkRequest,
    RatingRequest,
    RestoreRequest,
    RetiredImportRequest,
    RetireRequest,
    ReviewRequest,
    SchedulerRequest,
    StartRequest,
    TakeOverRequest,
    VerdictRequest,
    WindowRequest,
    _Writer,
)
from starpulse.event_log import rating_events

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.scheduler.adapters.remote import Remote
    from starpulse.scheduler.adapters.runtime import Runtime

logger = logging.getLogger(__name__)

#: Modes `POST /api/start` accepts; `interactive` is the Start-session default.
_START_MODES = frozenset({"interactive", "headless"})

#: Who may press Run now, loopback and the RFC 1918 ranges as (octets, prefix): the page is never
#: exposed to the internet, so a LAN browser needs no token (the React/Vite ADR).
_LAN = (
    ipaddress.ip_network("::1"),
    *(
        ipaddress.ip_network((bytes(octets), prefix))
        for octets, prefix in (
            ((127, 0, 0, 0), 8),
            ((10, 0, 0, 0), 8),
            ((172, 16, 0, 0), 12),
            ((192, 168, 0, 0), 16),
        )
    ),
)
#: The longest title a create accepts; a title is one line on a card, not a description.
_TITLE_MAX = 300
_REF = "ref:"  # a dependency naming a sibling in the same batch create by its `ref`
#: Saves hold this from reading a task's current record to writing, so two browsers saving one task cannot both pass the stale check.
_EDIT_LOCK = threading.Lock()
#: The verdicts a post-merge check takes, as a request spells them and as the comment records them.
_VERDICTS = {"pass": "PASS", "miss": "MISS"}
#: How long a task write waits, in seconds, for a restarted instance's replay to place its task before it answers 503.
REPLAY_WAIT_S = 5.0


def _held(feed: BoardFeed, task: str) -> dict | None:
    """The open task `task` as the feed holds it (a cold done task as its stub), waiting up to `REPLAY_WAIT_S` for a
    replay that has not placed it.

    A restarted instance serves before it has read its stream, when a task it holds is absent only because the replay
    has not reached it; the wait ends at the replay, and a feed that is not replaying answers at once.
    """
    if (agent := feed.held(task)) is None and feed.wait_replayed(REPLAY_WAIT_S):
        agent = feed.held(task)
    return agent


def _not_held(feed: BoardFeed, task: str) -> tuple[int, dict[str, str]]:
    """The refusal for a task `_held` did not find: 503, which a client sends again, while the replay has not ended,
    else 404."""
    if feed.wait_replayed(0):
        return 404, {"error": f"{task} is not on the board"}
    return 503, {"error": f"{task} is not on the board yet: the board is replaying its feed, retry"}


def _on_lan(source: str) -> bool:
    return any(ipaddress.ip_address(source) in net for net in _LAN)


def _lan_refusal(what: str) -> tuple[int, dict[str, str]]:
    """The 403 for `what` written from an address beyond the LAN."""
    return 403, {"error": f"{what} answers only loopback and private network (RFC 1918) browsers"}


def _invalid(error: ValidationError) -> tuple[int, dict[str, str]]:
    """The 400 for a body its request model refuses: the first fault, with the field it is in."""
    fault = error.errors()[0]
    where = ".".join(str(part) for part in fault["loc"])
    return 400, {"error": f"invalid request: {where + ': ' if where else ''}{fault['msg']}"}


type _Answer = tuple[int, Any]


def _write[R: BaseModel, **P](
    model: type[R], what: str
) -> Callable[[Callable[Concatenate[R, P], _Answer]], Callable[Concatenate[str, bytes, P], _Answer]]:
    """Make a handler of a parsed `model` into a write route's: `what` is refused 403 from beyond the LAN, a body
    `model` refuses is the one 400 `_invalid` words, and the handler takes the parsed request in the body's place."""

    def decorate(handler: Callable[Concatenate[R, P], _Answer]) -> Callable[Concatenate[str, bytes, P], _Answer]:
        @functools.wraps(handler)
        def parsed(source: str, raw: bytes, *args: P.args, **kwargs: P.kwargs) -> _Answer:
            if not _on_lan(source):
                return _lan_refusal(what)
            try:
                request = model.model_validate_json(raw, strict=True)
            except ValidationError as error:
                return _invalid(error)
            return handler(request, *args, **kwargs)

        return parsed

    return decorate


def write_refusal(origin: str | None, host: str | None, content_type: str | None) -> tuple[int, dict[str, str]] | None:
    """The refusal of a write that may have been sent by another web page, or None when it may go on.

    A page the operator opens reaches this server from the operator's own address, so the source check alone lets it
    write. A browser names the page's origin on a cross-site write, so an `origin` that is not this server's own (`host`
    is the `Host` header it was sent to) is 403, and `null` with it. A write must also say it is JSON: a form or a
    `text/plain` post, the cross-site requests a browser sends without asking first, is 415. The CLI sends no origin.
    """
    if origin is not None and urlsplit(origin).netloc != host:
        return 403, {"error": "A write answers only a page this server served: its origin is not this server's"}
    if (content_type or "").partition(";")[0].strip().lower() != "application/json":
        return 415, {"error": "A write must be sent as Content-Type: application/json"}
    return None


def run_dag(
    source: str, name: str, starts: Mapping[str, Callable[[str], str]], run_safe: Collection[str]
) -> tuple[int, dict[str, str]]:
    """Start the workflow `name` (`<instance>/<workflow>`) through its instance's `starts` entry, when there is one and
    `run_safe` holds it, for a browser at `source`: the HTTP status and JSON body to answer with."""
    if not _on_lan(source):
        return 403, {"error": "Run now answers only loopback and private network (RFC 1918) browsers"}
    instance, _, workflow = name.partition("/")
    if (start := starts.get(instance)) is None:
        return 404, {"error": f"no adapter can start {name}"}
    if name not in run_safe:
        return 404, {"error": f"{name} is not declared run-safe"}
    try:
        return 200, {"runId": start(workflow)}
    except StartFailedError as exc:
        return 502, {"error": str(exc)}


def rerun_dag(
    source: str,
    name: str,
    feed: BoardFeed,
    reruns: Mapping[str, Callable[[str, Mapping[str, str]], str]],
    run_safe: Collection[str],
) -> tuple[int, dict[str, str]]:
    """Start the run-safe workflow `name` again with its force parameter set and the commit its newest unresolved
    failure applied, through its instance's `reruns` entry, for a browser at `source`: the HTTP status and JSON body.

    A forced failure clears only on a green forced run that covers it, so the rerun carries the failed run's own
    commit parameters (`after`, `before`, `task`) and nothing else it was given.
    """
    if not _on_lan(source):
        return 403, {"error": "Rerun answers only loopback and private network (RFC 1918) browsers"}
    instance, _, workflow = name.partition("/")
    if (rerun := reruns.get(instance)) is None:
        return 404, {"error": f"no adapter can start {name}"}
    if name not in run_safe:
        return 404, {"error": f"{name} is not declared run-safe"}
    if (keys := feed.commit_keys(instance)) is None or not keys.force:
        return 409, {
            "error": f"{instance} declares no force parameter in [runs.commit]: a forced rerun is not possible"
        }
    if (failure := feed.open_failure(name)) is None:
        return 409, {"error": f"{name} has no unresolved failure"}
    carried = {key: failure["params"][key] for key in (keys.after, keys.before, keys.task) if key in failure["params"]}
    try:
        return 200, {"runId": rerun(workflow, {keys.force: "1", **carried})}
    except StartFailedError as exc:
        return 502, {"error": str(exc)}


class _Who(NamedTuple):
    """Who makes a write: its actor, and the session and harness it names, each empty when it names none."""

    actor: str
    session: str
    harness: str

    @property
    def created_by(self) -> str:
        """What a create stamps in the task: `<harness>:<session>`, or `anonymous` when the write names no session."""
        return f"{self.harness}:{self.session}" if self.session and self.harness else self.session or ANONYMOUS


def _who(request: _Writer) -> _Who:
    """Who `request` names as its writer.

    A write that names no actor is an agent's when it names a session and anonymous when it names none: never the
    operator, whom only the page names.
    """
    session = (request.session or "").strip()
    return _Who((request.actor or (AGENT if session else ANONYMOUS)).strip(), session, (request.harness or "").strip())


class _ClaimBody(ClaimRequest):
    """A claim names its session, the opaque string that holds the task."""

    session: NonBlank


def _record_written(feed: BoardFeed | None, task: str | None, who: _Who, write: Callable[[], Written]) -> Written:
    """Run `write` of `task` (None: the task the write makes, named by its output) and, when it put the task in a lane,
    record that lane change with `who` as its actor, session and harness.

    The feed's placing is held from the write to the record, so the board's poll that places the change the moment the
    file lands finds it recorded and records nothing more: a write refused, or one that moves no lane, records nothing.
    """
    with feed.recording if feed is not None else contextlib.nullcontext():
        written = write()
        if feed is not None and written.ok and written.lane:
            feed.record_written(
                task or written.output,
                written.lane,
                written.at or time.time(),
                (who.actor, who.session, who.harness),
            )
    return written


@_write(MoveRequest, "Moving a task")
def move_task(request: MoveRequest, feed: BoardFeed, writer: MoveWriter) -> tuple[int, dict[str, Any]]:
    """Move the task `request` names, or each of its `tasks`, to the column it names, through `writer`: the HTTP status
    and JSON body. A batch answers 200 with the tasks moved and each refused one's error, so one refusal leaves the
    others moved.

    The board machine's exits from the task's state decide which columns are offered; the writer decides which
    it accepts, so a guard that changed since the snapshot still refuses.
    """
    who = _who(request)
    if request.task is not None:
        return _move_one(feed, request.task, request.to, who, writer)
    if request.tasks is None:
        return 400, {"error": "invalid request: task: Field required"}
    moved, refused = [], {}
    for task in request.tasks or ():
        status, body = _move_one(feed, task, request.to, who, writer)
        if status == 200:
            moved.append(task)
        else:
            refused[task] = body["error"]
    return 200, {"moved": moved, "refused": refused}


def _move_one(feed: BoardFeed, task: str, column: str, who: _Who, writer: MoveWriter) -> tuple[int, dict[str, Any]]:
    """Move the `task` the board holds to `column` as `who` for `move_task`: the HTTP status and JSON body."""
    if (agent := _held(feed, task)) is None:
        return _not_held(feed, task)
    return _move(feed, agent, task, column, who, writer)


def _status(column: str) -> str:
    """The status a board column is written as; the board spells it as its lanes do."""
    return column.replace("_", " ").title()


def _move_refusal(agent: dict, task: str, column: str, who: _Who) -> tuple[int, dict[str, str]] | None:
    """The 409 for a move to `column` that the machine does not offer `who` from the task's state, else None."""
    moves = agent.get("moves", {})
    if column not in moves:  # a cold done task holds no moves
        offered = f"its moves are {', '.join(sorted(moves))}" if moves else "it has no moves"
        return 409, {"error": f"{task} cannot move from {agent['state']} to {column}: {offered}"}
    if not (move := Move.model_validate(agent["moves"][column])).permits(who.actor):
        return 409, {"error": move.for_actor(who.actor).reason, "skill": move.skill}
    return None


def _move(
    feed: BoardFeed, agent: dict, task: str, column: str, who: _Who, writer: MoveWriter
) -> tuple[int, dict[str, str]]:
    """Move the held task `agent` to `column` as `who` through `writer`: the HTTP status and JSON body of the move."""
    if (refused := _move_refusal(agent, task, column, who)) is not None:
        return refused
    status = _status(column)
    written = _record_written(
        feed,
        task,
        who,
        lambda: writer(task, status, who.actor, who.session) if who.session else writer(task, status, who.actor),
    )
    if written.unavailable:
        return 501, {"error": written.output}
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "to": column, **({"advice": written.advice} if written.advice else {})}


@_write(_ClaimBody, "Claiming a task")
def claim_task(request: _ClaimBody, feed: BoardFeed, writer: MoveWriter) -> tuple[int, dict[str, str]]:
    """Move the task `request` names to In Progress holding the session it names: the HTTP status and JSON body.

    The holder is an opaque string. A task already In Progress under that holder answers 200 without a write; under
    another, or when the holder already has another task In Progress, it is refused 409 naming the holder or the task.
    """
    task, who = request.task, _who(request)
    if (agent := _held(feed, task)) is None:
        return _not_held(feed, task)
    working = feed.roles.working
    held = {"task": task, "to": working, "assignee": who.session}
    if agent["state"] == working:
        if agent.get("assignee") == who.session:
            return 200, held
        return 409, {"error": f"{task} is already In Progress, held by {agent.get('assignee') or 'no session'}"}
    others = [a["id"] for a in feed.open_tasks() if a["state"] == working and a.get("assignee") == who.session]
    if others:
        return 409, {
            "error": f"this session already holds {others[0]} In Progress: park it, defer it or finish it before "
            f"claiming {task}"
        }
    status, body = _move(feed, agent, task, working, who, writer)
    return (200, {**body, "assignee": who.session}) if status == 200 else (status, body)


class _Refusal(Exception):
    """A lifecycle write refused before it is made: the HTTP status and JSON body to answer with."""

    def __init__(self, status: int, body: dict[str, str]) -> None:
        super().__init__(body["error"])
        self.answer = (status, body)


def _lifecycle_edit(
    feed: BoardFeed,
    task: str,
    column: str,
    who: _Who,
    comment: str,
    read: TaskReader,
    edit: TaskEditor,
    plan: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    """Move `task` to `column` in one `edit` of the fields `plan` draws from its current record, as `who`.

    The board's rules judge the record the edit makes, so a refusal returns their reason and skill with nothing written;
    a `plan` that refuses raises `_Refusal`.
    """
    with _EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        try:
            changes = {"status": _status(column), **plan(current)}
        except _Refusal as refusal:
            return refusal.answer
        written = _record_written(feed, task, who, lambda: edit(task, changes, comment, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "to": column}


def _section_set(description: str, heading: str, content: str) -> str:
    """`description` with its `## <heading>` section replaced by `content`, or ending with it when it had none."""
    kept = re.sub(rf"^## {re.escape(heading)}\s*$.*?(?=^## |\Z)", "", description, flags=re.M | re.S)
    return f"{kept.strip()}\n\n## {heading}\n\n{content.strip()}".strip()


def _wait_on_tasks(feed: BoardFeed, task: str, current: dict[str, Any], ids: Any) -> dict[str, Any]:
    """The edit that makes the task wait on the tasks `ids` names, kept after the dependencies it has."""
    if not (isinstance(ids, list) and ids and all(isinstance(name, str) and name.strip() for name in ids)):
        raise _Refusal(400, {"error": 'untilTask needs a non-empty list of task ids: {"untilTask": ["TASK-N"]}'})
    waits = list(dict.fromkeys(name.strip() for name in ids))
    for name in waits:
        if name.casefold() == task.casefold():
            raise _Refusal(409, {"error": f"{task} cannot wait on itself"})
        if feed.is_done(name):
            raise _Refusal(409, {"error": f"{name} is already Done: there is nothing to wait for"})
        if _held(feed, name) is None:
            raise _Refusal(*_not_held(feed, name))
    return {"dependencies": list(dict.fromkeys([*current["dependencies"], *waits]))}


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
        raise _Refusal(400, {"error": 'until needs a non-empty list of criteria, each with a unique "id" and a "kind"'})
    if open_ := [name for name in current["dependencies"] if not feed.is_done(name)]:
        raise _Refusal(
            409,
            {"error": f"{task} already waits on {', '.join(open_)}; a task is gated by one reason, never both"},
        )
    block = "```yaml\n" + yaml.safe_dump({"start_criteria": found}, sort_keys=False) + "```"
    return {
        "description": _section_set(current["description"], "Start Criteria", block),
        **({"dependencies": []} if current["dependencies"] else {}),  # Done dependencies gate nothing
    }


def _wait_on_operator(current: dict[str, Any], reason: Any) -> dict[str, Any]:
    """The edit that records `reason` as what only the operator can clear."""
    if not _nonblank(reason):
        raise _Refusal(400, {"error": "operator needs the reason, in text, that only the operator can clear"})
    return {"description": _section_set(current["description"], "Needs attention", reason)}


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


@_write(ParkRequest, "Parking a task")
def park_task(
    request: ParkRequest, feed: BoardFeed, read: TaskReader | None, edit: TaskEditor | None
) -> tuple[int, dict[str, Any]]:
    """Park the In Progress task `request` names for the one reason it names: the HTTP status and JSON body.

    The reason picks the lane and writes its gate in the same edit: `untilTask` adds dependencies and `until` writes the
    Start Criteria block, both to Waiting, and `operator` writes the Needs attention section to Needs attention. The
    machine must offer the writer that lane, and the board's rules judge the record the edit makes.
    """
    task, comment, who = request.task, request.comment or "", _who(request)
    reasons = [key for key in _PARK_REASONS if key in request.model_fields_set]
    if len(reasons) != 1:
        return 400, _BAD_PARK
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if (agent := _held(feed, task)) is None:
        return _not_held(feed, task)
    if agent["state"] != feed.roles.working:
        return 409, {"error": f"only an In Progress task can be parked: {task} is {agent['state']}"}
    reason = reasons[0]
    column, value = _park_lane(feed, reason), getattr(request, reason)
    if column is None:
        return 409, {"error": f"this board's machine has no lane to park {task} in for {reason}"}
    if (refused := _move_refusal(agent, task, column, who)) is not None:
        return refused
    plans = {
        "untilTask": lambda current: _wait_on_tasks(feed, task, current, value),
        "until": lambda current: _wait_on_criteria(feed, task, current, value),
        "operator": lambda current: _wait_on_operator(current, value),
    }
    return _lifecycle_edit(feed, task, column, who, comment, read, edit, plans[reason])


_BAD_REVIEW = {"error": "references must each be a nonblank pull request link"}


@_write(ReviewRequest, "Reviewing a task")
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
    comment, who = request.comment or "", _who(request)
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if (agent := _held(feed, task)) is None:
        return _not_held(feed, task)
    review = feed.roles.review
    if review is None:
        return 409, {"error": f"this board's machine has no lane to move {task} to for review"}
    if (refused := _move_refusal(agent, task, review, who)) is not None:
        return refused

    def plan(current: dict[str, Any]) -> dict[str, Any]:
        references = list(dict.fromkeys([*current["references"], *(link.strip() for link in links)]))
        return {
            **({"references": references} if references != current["references"] else {}),
            **({"finalSummary": summary.strip()} if summary.strip() else {}),
        }

    return _lifecycle_edit(feed, task, review, who, comment, read, edit, plan)


def task_record(feed: BoardFeed, read: TaskReader | None, task: str) -> tuple[int, dict[str, Any]]:
    """The full record of `task` from the board's reader: the HTTP status and JSON body.

    The record is keyed by the task's editable fields, which the snapshot's small entry does not carry; the page
    opens it with this and sends it back as the `base` of an edit. Reading is not LAN-limited, like the snapshot.
    """
    if read is None:
        return 404, {"error": "this board cannot read a task's full record"}
    if _held(feed, task) is None:
        return _not_held(feed, task)
    if (record := read(task)) is None:
        return 404, {"error": f"{task} has no record to read"}
    return 200, {"task": task, "record": record}


#: The edit change that adds a line to the task's notes rather than setting a record field.
_APPEND_NOTES = "appendNotes"


@_write(EditRequest, "Editing a task")
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
    who = _who(request)
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if _held(feed, task) is None:
        return _not_held(feed, task)
    with _EDIT_LOCK:
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
            written = _record_written(feed, task, who, lambda: edit(task, todo, comment, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    changed = ("notes" if field == _APPEND_NOTES else field for field in todo)
    return 200, {"task": task, "changed": list(dict.fromkeys(changed))}


@_write(ArchiveRequest, "Archiving a task")
def archive_task(request: ArchiveRequest, feed: BoardFeed, archive: TaskArchiver | None) -> tuple[int, dict[str, Any]]:
    """Archive the task `request` names, or each of its `tasks`, from whichever column it is in, through `archive`: the
    HTTP status and JSON body. A batch answers 200 with the tasks archived and each refused one's error, so one refusal
    leaves the others archived.

    A non-empty `reason` is the writer's to record on the task. The card leaves its column when the board adapter
    next reports the task archived, not on this answer.
    """
    if archive is None:
        return 404, {"error": "this board does not archive tasks"}
    reason, who = request.reason or "", _who(request)
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


def _archive_one(feed: BoardFeed, archive: TaskArchiver, task: str, reason: str, who: _Who) -> tuple[int, dict[str, Any]]:
    """Archive one `task` for `archive_task`: the HTTP status and JSON body a single-task request answers."""
    if _held(feed, task) is None:
        return _not_held(feed, task)
    written = _record_written(feed, task, who, lambda: archive(task, reason, actor=who.actor))
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


@_write(RatingRequest, "Recording a rating")
def record_rating(request: RatingRequest, feed: BoardFeed) -> tuple[int, dict[str, Any]]:
    """Record `request`'s change of a task's pass/fail rating as one entry of the `task:ratings` stream, and answer the
    task's rating now with its change count. A change the stream does not take is 503: the control shows
    "Rating not saved.".
    """
    who = _who(request)
    reason = (request.reason or "").strip()
    fields = rating_events.change(request.task, request.verdict, reason, time.time(), *who)
    rated = feed.rate(fields)
    if rated is None:
        return 503, {"error": "rating not saved"}
    return 200, {"task": request.task, "verdict": request.verdict, "reason": rated["reason"], "changes": rated["changes"]}


@_write(VerdictRequest, "Recording a verdict")
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
    evidence, who = request.evidence or "", _who(request)
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if _held(feed, task) is None:
        return _not_held(feed, task)
    if verdict == "miss" and _held(feed, fix) is None:
        return _not_held(feed, fix)
    with _EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        if refusal := _unjudged(task, current, check):
            return 409, {"error": refusal}
        comment = post_merge_checks.verdict_comment(check, _VERDICTS[verdict], evidence, fix)
        written = _record_written(feed, task, who, lambda: edit(task, {}, comment, actor=who.actor))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "check": check, "verdict": _VERDICTS[verdict], **({"fix": fix} if fix else {})}


@_write(MissRequest, "Recording a miss")
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
    task, check, evidence, who = request.task, request.check, request.evidence or "", _who(request)
    if read is None or edit is None or archive is None or create is None:
        return 404, {"error": "this board does not edit, archive and create tasks"}
    if _held(feed, task) is None:
        return _not_held(feed, task)
    with _EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        if refusal := _unjudged(task, current, check):
            return 409, {"error": refusal}
        status, body = _create(request.fix, who, create, feed, {})
        if status != 201:
            return status, body
        comment = post_merge_checks.verdict_comment(check, "MISS", evidence, body["task"])
        written = _record_written(feed, task, who, lambda: edit(task, {}, comment, actor=who.actor))
        if not written.ok:
            archive(body["task"], f"the MISS verdict on {task} {check} was refused: {written.output}", actor=who.actor)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "check": check, "verdict": "MISS", "fix": body["task"]}


@_write(CompleteRequest, "Completing a task")
def complete_task(
    request: CompleteRequest, feed: BoardFeed, complete: TaskCompleter | None
) -> tuple[int, dict[str, Any]]:
    """Complete the Done task `request` names through `complete`: the HTTP status and JSON body.

    The board's writer refuses a task that is not Done, which answers 409 with the writer's reason and skill.
    """
    task = request.task
    if complete is None:
        return 404, {"error": "this board does not complete tasks"}
    if _held(feed, task) is None:
        return _not_held(feed, task)
    written = complete(task)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


@_write(RestoreRequest, "Restoring a task")
def restore_task(request: RestoreRequest, feed: BoardFeed, restore: TaskRestorer | None) -> tuple[int, dict[str, Any]]:
    """Return the archived task `request` names to the board's tasks through `restore`: the HTTP status and JSON body.

    The restore places the task in a lane, so its writer is noted on the feed as any other move's is. The writer owns
    every other refusal (no archived file, the number already open, the name taken), which answers 409 with its reason.
    """
    task, who = request.task, _who(request)
    if restore is None:
        return 404, {"error": "this board does not restore tasks"}
    written = _record_written(feed, task, who, lambda: restore(task))
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


@_write(TakeOverRequest, "Taking a task over")
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


@_write(RetireRequest, "Retiring a task")
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


@_write(RetiredImportRequest, "Importing a retired task")
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
    spec: CreateSpec, who: _Who, create: TaskCreator | None, feed: BoardFeed | None, siblings: Mapping[str, str]
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
            siblings.get(item.removeprefix(_REF), item) if item.startswith(_REF) else item
            for item in details["dependencies"]
        ]
        if unresolved := [item for item in dependencies if item.startswith(_REF)]:
            return 409, {"error": f"depends on {', '.join(unresolved)}, which no earlier task in the batch created"}
        details["dependencies"] = dependencies
    # the id is the writer's to choose, so the lane is recorded under the id the write returns
    written = _record_written(
        feed, None, who, lambda: create(title, {**details, "created_by": who.created_by}, actor=who.actor)
    )
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 201, {"task": written.output}


@_write(CreateRequest, "Creating a task")
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
    who = _who(request)
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


@_write(MilestoneCreateRequest, "Adding a milestone")
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


@_write(MilestoneEditRequest, "Editing a milestone")
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


@_write(MilestoneArchiveRequest, "Archiving a milestone")
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


@_write(DocCreateRequest, "Adding a doc")
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


@_write(DocEditRequest, "Editing a doc")
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


@_write(DocArchiveRequest, "Archiving a doc")
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


@_write(DocRestoreRequest, "Restoring a doc")
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


@_write(StartRequest, "Starting a session")
def start_task(
    request: StartRequest,
    feed: BoardFeed,
    assign: AssigneeWriter,
    start_session: Callable[..., str] | None,
    harnesses: Harnesses | None = None,
    clock: Callable[[], float] = time.time,
) -> tuple[int, dict[str, Any]]:
    """Start a session for the task `request` names, on the profile and harness it names: the HTTP status and JSON
    body.

    A changed profile is saved through the guarded writer first, since the session-start service reads the
    profile from the task. `harness` selects which configured harness opens the session; `mode` defaults to
    `interactive`. `at` is when the start began, so the page applies only a refused claim made after it.
    """
    task = request.task
    profile = request.profile if request.profile is not None else request.assignee
    harness = "claude" if request.harness is None else request.harness
    mode = "interactive" if request.mode is None else request.mode
    named = {} if request.actor is None else {"actor": request.actor.strip()}
    if profile is None:
        return 400, {"error": 'a start needs {"task": "TASK-N", "profile": "@agent-<tier>-<effort>"}'}
    if not harness:
        return 400, {"error": "harness must be a non-empty name from agent-harnesses.toml"}
    if mode not in _START_MODES:
        return 400, {"error": 'mode must be "interactive" or "headless"'}
    if start_session is None:
        return 404, {"error": "no session-start service is configured (session_start_url)"}
    if harnesses is not None and harnesses.harnesses:
        if (chosen := harnesses.harnesses.get(harness)) is None:
            return 409, {"error": f"{harness} is not a configured harness"}
        if not chosen.sessions:
            return 409, {"error": chosen.reason or f"{harness} cannot start a session"}
    if (agent := _held(feed, task)) is None:
        return _not_held(feed, task)
    startable = feed.roles.startable
    if agent["state"] not in startable:
        listed = [state for state in feed.roles.roles if state in startable]
        names = " or ".join(filter(None, [", ".join(listed[:-1]), *listed[-1:]]))
        return 409, {"error": f"{task} is in {agent['state']}: a session starts only a {names} task"}
    at = clock()
    if profile != agent["model"] and not (written := assign(task, profile, **named)).ok:
        return 409, {"error": written.output, "skill": written.skill}
    try:
        try:
            session = start_session(task, harness=harness, mode=mode)
        except TypeError:
            session = start_session(task)  # a one-arg starter from before harness/mode
        return 200, {"task": task, "url": session, "at": at}
    except StartFailedError as exc:
        return 502, {"error": str(exc)}


@_write(WindowRequest, "The history window")
def _set_window(request: WindowRequest, window: HistoryWindow) -> tuple[int, dict[str, Any]]:
    try:
        window.set(request.hours)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, window.state()


def history_window(source: str, method: str, raw: bytes, window: HistoryWindow) -> tuple[int, dict[str, Any]]:
    """Read (`GET`), set (`PUT {"hours": N}`) or reset (`DELETE`) the shared history window for a browser at `source`:
    the HTTP status and JSON body, which is the window's state, or the refusal."""
    if method == "PUT":
        return _set_window(source, raw, window)
    if not _on_lan(source):
        return _lan_refusal("The history window")
    if method == "DELETE":
        window.reset()
    return 200, window.state()


_SCHEDULER_USAGE = (
    'the scheduler takes {"enabled": true|false}, {"harness": "<name>"} and/or '
    '{"quietHours": {"start", "end", "timezone"}|null}'
)


@_write(SchedulerRequest, "The scheduler switch")
def _put_scheduler(request: SchedulerRequest, runtime: Runtime | Remote) -> tuple[int, dict[str, Any]]:
    named = request.model_fields_set
    if not named or ("enabled" in named and request.enabled is None):
        return 400, {"error": _SCHEDULER_USAGE}
    try:
        if "harness" in named:
            runtime.set_harness(request.harness)
        if "quietHours" in named:
            quiet = request.quietHours
            runtime.set_quiet_hours(None if quiet is None else quiet.model_dump())
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if request.enabled is not None:
        runtime.set_enabled(request.enabled)
    return 200, runtime.served_status()


def scheduler(source: str, method: str, raw: bytes, runtime: Runtime | Remote | None) -> tuple[int, dict[str, Any]]:
    """Read (`GET`) whether the scheduler admits tasks, which harness it starts on, its quiet hours and each capacity
    dimension's use against its limit, or set (`PUT {"enabled": bool}`, `PUT {"harness": "<name>"}`,
    `PUT {"quietHours": {...} | null}`, or any combination) those settings, for a browser at `source`.

    Settings are kept in the store the scheduler reads, so a PUT takes effect at the next admission and survives a
    restart. A read answers any address, as every read does; a write answers only loopback and RFC 1918. A body with
    anything wrong changes nothing.
    """
    if runtime is None:
        return 404, {"error": "this instance runs no scheduler"}
    if method == "PUT":
        return _put_scheduler(source, raw, runtime)
    return 200, runtime.served_status()
