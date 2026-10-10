"""The write routes of StarPulse's HTTP server: each handler takes the request's source, body and the seam it writes through,
and answers the HTTP status and JSON body.

`starpulse._internal.server.server` routes a request here after its write guard (`write_refusal`: 415 for a body that is not JSON, 403 for
another site's origin) and dispatches to these; the read responses, the stream and the assembly stay there. The routes:

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
POST /api/move     {task, to[, actor]}: set a Board task's status through the board adapter's writer, as `actor`
                   (`operator`, the page's identity, when absent). An actor outside the event's declared writers
                   is refused 409 before the writer is asked; a board with no writer answers 501
GET /api/task/<id> {task, record}: every editable field of a task from the board's `read`, which the snapshot's
                   entry does not carry; 404 when the board cannot read or the task is not on it
POST /api/edit     {task, base, changes, comment[, actor]}: one write of every change through the board's `edit`. 409 with the
                   stale fields and their current values when any changed field no longer equals its `base`, or with
                   the writer's refusal and its skill; 403 outside loopback and RFC 1918. A GET answers 405
POST /api/archive  {task, reason[, actor]}: archive a task from any lane through the board's `archive`; refusals as for
                   an edit
POST /api/complete {task}: move a Done task into the board's completed tasks through its `complete`; refusals
                   as for an edit (409 for a task that is not Done), 404 when the board does not complete or the task is
                   not on it
POST /api/restore  {task}: return an archived task to the board's tasks, unchanged, through its `restore`; 409 with the
                   writer's refusal for a task that is not archived, is already open or completed, or whose file name is
                   taken, 404 when the board does not restore
POST /api/tasks    {title, description, priority, labels, milestone, assignee, dependencies, acceptanceCriteria[,
                   actor]}: create
                   a task in the board's starting lane through the board's `create`, and answer 201 {task}
                   with its id; only the title is required. 400 for a missing, blank or over-long title or a detail of
                   the wrong kind, 403 outside loopback and RFC 1918, 404 when the board
                   does not create (the snapshot's `capabilities.create` says which). A GET answers 405
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
POST /api/start    {task, assignee[, actor]}: start a task's session at `session_start_url` (see Start in the README)
GET /api/forwarding
                   what this instance's forwarder would send the hub next, as the Admin view lists it: {configured,
                   url, optIn, names, refused, lastSent, problem, next, more, contract}. `next` holds the first entries
                   past the forwarder's cursor, each cut as the batch is cut; `{"configured": false}` without a
                   `[forward]` block. 403 outside loopback and RFC 1918
PUT /api/forwarding {opt_in: bool}: let a person's name leave this instance, or stop it, by writing the opt-in file the
                   forwarder reads before every batch, and answer the status as a GET does; 400 for anything but a
                   boolean, 404 without a `[forward]` block, 403 outside loopback and RFC 1918
GET /api/autopilot {enabled, sampledAt, dimensions}: whether the autopilot admits tasks, when capacity was last sampled
                   and, for `cpu`, `memory`, `sessions` and `review`, each dimension's {name, use, limit}; no
                   dimensions before the first sample
PUT /api/autopilot {enabled: bool}: switch admission on or off by writing the file the autopilot reads, and answer the
                   status as a GET does; 400 for anything but a boolean, 403 outside loopback and RFC 1918
"""

from __future__ import annotations

import ipaddress
import json
import logging
import threading
import time
from collections.abc import Callable, Collection, Mapping
from typing import Any
from urllib.parse import urlsplit

from starpulse._internal.board.seam import (
    AssigneeWriter,
    Board,
    OPERATOR,
    MoveWriter,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskRestorer,
)
from starpulse._internal.autopilot.runtime import Runtime
from starpulse._internal.hub.forward import Forwarder
from starpulse.contracts.adapters import Move, StartFailedError
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.config.history_window import HistoryWindow
from starpulse._internal.eventlog.history import HistoryStore

logger = logging.getLogger(__name__)

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
#: The details a create takes besides its title, as one text value or a list of them.
_CREATE_TEXT = ("description", "priority", "milestone", "assignee")
_CREATE_LISTS = ("labels", "dependencies", "acceptanceCriteria")
_PRIORITIES = frozenset({"high", "medium", "low"})
_CREATE_KINDS = {
    "priority": "high, medium or low",
    "labels": "a list of text",
    "dependencies": "a list of text",
    "acceptanceCriteria": "a list of nonblank text",
}
#: Saves hold this from reading a task's current record to writing, so two browsers saving one task cannot both pass the stale check.
_EDIT_LOCK = threading.Lock()
#: The lanes Start session moves a task out of: the spec's start question, never Review's send-back.
_STARTABLE = frozenset({"ready", "waiting", "needs_attention"})


def _on_lan(source: str) -> bool:
    return any(ipaddress.ip_address(source) in net for net in _LAN)


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


_BAD_ACTOR = {
    "error": 'a write may name its "actor", a non-empty text, as `operator`, `agent` or `<instance>/<workflow>`'
}


def _named_actor(request: Any) -> dict[str, str] | None:
    """`{"actor": name}` for a request that names its actor, `{}` for one that names none and None for a name that is not
    text. A writer is called with the keyword only when the request named one, so a writer that predates actors, or a
    page that never names its own, is called as it always was."""
    if not isinstance(request, dict) or "actor" not in request:
        return {}
    actor = request["actor"]
    return {"actor": actor.strip()} if isinstance(actor, str) and actor.strip() else None


def move_task(source: str, raw: bytes, feed: BoardFeed, writer: MoveWriter) -> tuple[int, dict[str, str]]:
    """Move a task to the column `raw` names, through `writer`, for a browser at `source`: the HTTP status and JSON body.

    The board machine's exits from the task's state decide which columns are offered; the writer decides which
    it accepts, so a guard that changed since the snapshot still refuses.
    """
    if not _on_lan(source):
        return 403, {"error": "Moving a task answers only loopback and private network (RFC 1918) browsers"}
    try:
        request = json.loads(raw)
        task, column = request["task"], request["to"]
        actor, session = request.get("actor", OPERATOR), request.get("session", "")
    except ValueError, TypeError, KeyError, AttributeError:
        task = column = actor = session = None
    if not all(isinstance(value, str) for value in (task, column, actor, session)):
        return 400, {
            "error": 'a move needs {"task": "TASK-N", "to": "<column>"} and may name an "actor" and a "session" (strings)'
        }
    if (agent := feed.task(task)) is None:
        return 404, {"error": f"{task} is not on the board"}
    if column not in agent["moves"]:
        return 409, {"error": f"{task} cannot move from {agent['state']} to {column}"}
    if not (move := Move.model_validate(agent["moves"][column])).permits(actor):
        return 409, {"error": move.for_actor(actor).reason, "skill": move.skill}
    status = column.replace("_", " ").title()
    written = writer(task, status, actor, session) if session else writer(task, status, actor)
    if written.unavailable:
        return 501, {"error": written.output}
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "to": column, **({"advice": written.advice} if written.advice else {})}


def task_record(feed: BoardFeed, read: TaskReader | None, task: str) -> tuple[int, dict[str, Any]]:
    """The full record of `task` from the board's reader: the HTTP status and JSON body.

    The record is keyed by the task's editable fields, which the snapshot's small entry does not carry; the page
    opens it with this and sends it back as the `base` of an edit. Reading is not LAN-limited, like the snapshot.
    """
    if read is None:
        return 404, {"error": "this board cannot read a task's full record"}
    if feed.task(task) is None:
        return 404, {"error": f"{task} is not on the board"}
    if (record := read(task)) is None:
        return 404, {"error": f"{task} has no record to read"}
    return 200, {"task": task, "record": record}


def edit_task(
    source: str, raw: bytes, feed: BoardFeed, read: TaskReader | None, edit: TaskEditor | None
) -> tuple[int, dict[str, Any]]:
    """Apply the edit `raw` names to a task through `edit` in one write, for a browser at `source`: the HTTP status and
    JSON body.

    `base` holds the value each changed field had when the page read the task. The edit is refused 409 when any
    changed field's current value differs, naming those fields with their current values, so another writer's
    change is never overwritten; fields the edit does not touch may differ. The writer refuses a whole edit or
    writes all of it, and its refusal carries the skill that satisfies it.
    """
    if not _on_lan(source):
        return 403, {"error": "Editing a task answers only loopback and private network (RFC 1918) browsers"}
    try:
        request = json.loads(raw)
        task, base, changes, comment = request["task"], request["base"], request["changes"], request.get("comment", "")
        named = _named_actor(request)
    except ValueError, TypeError, KeyError:
        task = base = changes = comment = named = None
    if not (
        isinstance(task, str) and isinstance(base, dict) and isinstance(changes, dict) and changes
    ) or not isinstance(comment, str):
        return 400, {
            "error": 'an edit needs {"task": "TASK-N", "base": {...}, "changes": {...}, "comment": "<optional>"}'
        }
    if named is None:
        return 400, _BAD_ACTOR
    if read is None or edit is None:
        return 404, {"error": "this board does not edit tasks"}
    if feed.task(task) is None:
        return 404, {"error": f"{task} is not on the board"}
    with _EDIT_LOCK:
        if (current := read(task)) is None:
            return 404, {"error": f"{task} has no record to read"}
        for field in changes:
            if field not in current:
                return 400, {"error": f"{field} is not an editable field of {task}"}
            if field not in base:
                return 400, {"error": f"the edit has no base for {field}"}
        if stale := [field for field in changes if current[field] != base[field]]:
            return 409, {
                "error": f"{task} changed since it was opened: {', '.join(stale)}",
                "stale": stale,
                "current": {field: current[field] for field in stale},
            }
        if not (todo := {field: value for field, value in changes.items() if value != current[field]}):
            return 200, {"task": task, "changed": []}
        written = edit(task, todo, comment, **named)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task, "changed": list(todo)}


def archive_task(source: str, raw: bytes, feed: BoardFeed, archive: TaskArchiver | None) -> tuple[int, dict[str, Any]]:
    """Archive the task `raw` names, from whichever column it is in, through `archive`, for a browser at `source`: the
    HTTP status and JSON body.

    A non-empty `reason` is the writer's to record on the task. The card leaves its column when the board adapter
    next reports the task archived, not on this answer.
    """
    if not _on_lan(source):
        return 403, {"error": "Archiving a task answers only loopback and private network (RFC 1918) browsers"}
    try:
        request = json.loads(raw)
        task, reason = request["task"], request.get("reason", "")
        named = _named_actor(request)
    except ValueError, TypeError, KeyError:
        task = reason = named = None
    if not isinstance(task, str) or not isinstance(reason, str):
        return 400, {"error": 'an archive needs {"task": "TASK-N", "reason": "<optional text>"}'}
    if named is None:
        return 400, _BAD_ACTOR
    if archive is None:
        return 404, {"error": "this board does not archive tasks"}
    if feed.task(task) is None:
        return 404, {"error": f"{task} is not on the board"}
    written = archive(task, reason, **named)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def complete_task(source: str, raw: bytes, feed: BoardFeed, complete: TaskCompleter | None) -> tuple[int, dict[str, Any]]:
    """Complete the Done task `raw` names through `complete`, for a browser at `source`: the HTTP status and JSON body.

    The board's writer refuses a task that is not Done, which answers 409 with the writer's reason and skill.
    """
    if not _on_lan(source):
        return 403, {"error": "Completing a task answers only loopback and private network (RFC 1918) browsers"}
    try:
        task = json.loads(raw)["task"]
    except ValueError, TypeError, KeyError:
        task = None
    if not isinstance(task, str):
        return 400, {"error": 'a complete needs {"task": "TASK-N"}'}
    if complete is None:
        return 404, {"error": "this board does not complete tasks"}
    if feed.task(task) is None:
        return 404, {"error": f"{task} is not on the board"}
    written = complete(task)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def restore_task(source: str, raw: bytes, restore: TaskRestorer | None) -> tuple[int, dict[str, Any]]:
    """Return the archived task `raw` names to the board's tasks through `restore`, for a browser at `source`: the HTTP
    status and JSON body.

    The writer owns every other refusal (no archived file, the number already open, the name taken), which answers 409 with
    its reason.
    """
    if not _on_lan(source):
        return 403, {"error": "Restoring a task answers only loopback and private network (RFC 1918) browsers"}
    try:
        task = json.loads(raw)["task"]
    except ValueError, TypeError, KeyError:
        task = None
    if not isinstance(task, str):
        return 400, {"error": 'a restore needs {"task": "TASK-N"}'}
    if restore is None:
        return 404, {"error": "this board does not restore tasks"}
    written = restore(task)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def _create_details(body: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """The filled details of a create body, trimmed, and the first field that is unknown or of the wrong kind, or ""."""
    details: dict[str, Any] = {}
    for field, value in body.items():
        if field in ("title", "actor"):
            continue
        if field in _CREATE_TEXT:
            ok = isinstance(value, str)
            value = value.strip() if ok else value
        elif field in _CREATE_LISTS:
            ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
            value = [item.strip() for item in value if item.strip()] if ok else value
            ok = ok and (field != "acceptanceCriteria" or len(value) == len(body[field]))
        else:
            return (
                {},
                f"{field} is not a task field; a create takes title, {', '.join((*_CREATE_TEXT, *_CREATE_LISTS))}",
            )
        if field == "priority" and ok and value:
            ok, value = value.lower() in _PRIORITIES, value.lower()
        if not ok:
            return {}, f"{field} must be {_CREATE_KINDS.get(field, 'text')}"
        if value:
            details[field] = value
    return details, ""


def create_task(source: str, raw: bytes, create: TaskCreator | None) -> tuple[int, dict[str, Any]]:
    """Create the task `raw` names in the board's starting lane through `create`, for a browser at `source`: the HTTP
    status and JSON body, which holds the new task's id.

    The card appears in its column when the board adapter next reports the task, not on this answer.
    """
    if not _on_lan(source):
        return 403, {"error": "Creating a task answers only loopback and private network (RFC 1918) browsers"}
    try:
        body = json.loads(raw)
        title = body["title"]
        named = _named_actor(body)
    except ValueError, TypeError, KeyError:
        body, title, named = {}, None, None
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > _TITLE_MAX:
        return 400, {"error": f'a create needs {{"title": "<1 to {_TITLE_MAX} characters>"}}'}
    if named is None:
        return 400, _BAD_ACTOR
    details, wrong = _create_details(body)
    if wrong:
        return 400, {"error": wrong}
    if create is None:
        return 404, {"error": "this board does not create tasks"}
    written = create(title.strip(), details, **named)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 201, {"task": written.output}


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


def _record_request(
    source: str, raw: bytes, action: str, noun: str
) -> tuple[dict[str, Any] | None, tuple[int, dict[str, Any]]]:
    """The JSON object `raw` holds for a milestone or doc write at `source`, or None with the refusal to answer."""
    if not _on_lan(source):
        return None, (
            403,
            {"error": f"{action} a {noun} answers only loopback and private network (RFC 1918) browsers"},
        )
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return None, (400, {"error": f"a {noun} write takes a JSON object"})
    return body, (200, {})


def create_milestone(source: str, raw: bytes, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Open the milestone `raw` names through the board's `create_milestone`, for a browser at `source`: the HTTP status
    and JSON body, which holds the new milestone's id. Only the title is required."""
    body, refusal = _record_request(source, raw, "Adding", "milestone")
    if body is None:
        return refusal
    title = body.get("title")
    if not isinstance(title, str) or not title.strip():
        return 400, {"error": 'an add needs {"title": "<text>"}'}
    if board is None or board.create_milestone is None:
        return 404, {"error": "this board does not create milestones"}
    written = board.create_milestone(title, {field: value for field, value in body.items() if field != "title"})
    if not written.ok:  # the writer refuses a detail it cannot store, or a title it cannot file
        return 400, {"error": written.output, "skill": written.skill}
    return 201, {"milestone": written.output}


def edit_milestone(source: str, raw: bytes, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Apply the `changes` `raw` names to a milestone through the board's `edit_milestone`, for a browser at `source`: the
    HTTP status and JSON body. `changed` names the fields whose value the edit changed; an edit that changes none writes
    nothing."""
    body, refusal = _record_request(source, raw, "Editing", "milestone")
    if body is None:
        return refusal
    milestone, changes = body.get("milestone"), body.get("changes")
    if not isinstance(milestone, str) or not isinstance(changes, dict) or not changes:
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


def archive_milestone(source: str, raw: bytes, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Archive the milestone `raw` names through the board's `archive_milestone`, for a browser at `source`: the HTTP status
    and JSON body."""
    body, refusal = _record_request(source, raw, "Archiving", "milestone")
    if body is None:
        return refusal
    if not isinstance(milestone := body.get("milestone"), str):
        return 400, {"error": 'an archive needs {"milestone": "m-N"}'}
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


def create_doc(source: str, raw: bytes, board: Board | None) -> tuple[int, dict[str, Any]]:
    """File the doc `raw` names through the board's `create_doc`, for a browser at `source`: the HTTP status and JSON
    body, which holds the new doc's id. Only the title is required."""
    body, refusal = _record_request(source, raw, "Adding", "doc")
    if body is None:
        return refusal
    title = body.get("title")
    if not isinstance(title, str) or not title.strip():
        return 400, {"error": 'a create needs {"title": "<text>"}'}
    if board is None or board.create_doc is None:
        return 404, {"error": "this board does not create docs"}
    written = board.create_doc(title, {field: value for field, value in body.items() if field != "title"})
    if not written.ok:  # the writer refuses a detail it cannot store, or a title it cannot file
        return 400, {"error": written.output, "skill": written.skill}
    return 201, {"doc": written.output}


def edit_doc(source: str, raw: bytes, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Apply the `changes` `raw` names to a doc through the board's `edit_doc`, for a browser at `source`: the HTTP status
    and JSON body. `changed` names the fields whose value the edit changed; an edit that changes none writes nothing."""
    body, refusal = _record_request(source, raw, "Editing", "doc")
    if body is None:
        return refusal
    doc, changes = body.get("doc"), body.get("changes")
    if not isinstance(doc, str) or not isinstance(changes, dict) or not changes:
        return 400, {"error": 'an update needs {"doc": "doc-N", "changes": {...}}'}
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


def archive_doc(source: str, raw: bytes, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Archive the doc `raw` names through the board's `archive_doc`, for a browser at `source`: the HTTP status and
    JSON body."""
    body, refusal = _record_request(source, raw, "Archiving", "doc")
    if body is None:
        return refusal
    if not isinstance(doc := body.get("doc"), str):
        return 400, {"error": 'an archive needs {"doc": "doc-N"}'}
    if board is None or board.read_doc is None or board.archive_doc is None:
        return 404, {"error": "this board does not archive docs"}
    if board.read_doc(doc) is None:
        return 404, {"error": f"{doc} is not an open doc"}
    written = board.archive_doc(doc)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"doc": doc}


def restore_doc(source: str, raw: bytes, board: Board | None) -> tuple[int, dict[str, Any]]:
    """Return the archived doc `raw` names to the folder it names under the board's docs through the board's
    `restore_doc`, for a browser at `source`: the HTTP status and JSON body.

    The writer owns every other refusal (no archived file, the id already open, the destination taken, a folder that is
    not a path of plain names), which answers 409 with its reason.
    """
    body, refusal = _record_request(source, raw, "Restoring", "doc")
    if body is None:
        return refusal
    folder = body.get("folder", "")
    if not isinstance(doc := body.get("doc"), str) or not isinstance(folder, str):
        return 400, {"error": 'a restore needs {"doc": "doc-N"} and, optionally, {"folder": "specs"}'}
    if board is None or board.restore_doc is None:
        return 404, {"error": "this board does not restore docs"}
    written = board.restore_doc(doc, folder)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"doc": doc}


def start_task(
    source: str,
    raw: bytes,
    feed: BoardFeed,
    assign: AssigneeWriter,
    start_session: Callable[[str], str] | None,
    clock: Callable[[], float] = time.time,
) -> tuple[int, dict[str, Any]]:
    """Start a session for the task `raw` names, on the assignee it names, for a browser at `source`: the HTTP status
    and JSON body.

    A changed assignee is saved through the guarded writer first, since the session-start service reads the
    profile from the task. `at` is when the start began, so the page applies only a refused claim made after it.
    """
    if not _on_lan(source):
        return 403, {"error": "Starting a session answers only loopback and private network (RFC 1918) browsers"}
    try:
        request = json.loads(raw)
        task, assignee = request["task"], request["assignee"]
        named = _named_actor(request)
    except ValueError, TypeError, KeyError:
        task = assignee = named = None
    if not isinstance(task, str) or not isinstance(assignee, str):
        return 400, {"error": 'a start needs {"task": "TASK-N", "assignee": "@agent-<tier>-<effort>"}'}
    if named is None:
        return 400, _BAD_ACTOR
    if start_session is None:
        return 404, {"error": "no session-start service is configured (session_start_url)"}
    if (agent := feed.task(task)) is None:
        return 404, {"error": f"{task} is not on the board"}
    if agent["state"] not in _STARTABLE:
        return 409, {
            "error": f"{task} is in {agent['state']}: a session starts only a ready, waiting or needs_attention task"
        }
    at = clock()
    if assignee != agent["model"] and not (written := assign(task, assignee, **named)).ok:
        return 409, {"error": written.output, "skill": written.skill}
    try:
        return 200, {"task": task, "url": start_session(task), "at": at}
    except StartFailedError as exc:
        return 502, {"error": str(exc)}


def history_window(source: str, method: str, raw: bytes, window: HistoryWindow) -> tuple[int, dict[str, Any]]:
    """Read (`GET`), set (`PUT {"hours": N}`) or reset (`DELETE`) the shared history window for a browser at `source`:
    the HTTP status and JSON body, which is the window's state, or the refusal."""
    if not _on_lan(source):
        return 403, {"error": "The history window answers only loopback and private network (RFC 1918) browsers"}
    if method == "PUT":
        try:
            hours = json.loads(raw)["hours"]
        except ValueError, TypeError, KeyError:
            return 400, {"error": 'a history window needs {"hours": N}'}
        try:
            window.set(hours)
        except ValueError as exc:
            return 400, {"error": str(exc)}
    elif method == "DELETE":
        window.reset()
    return 200, window.state()


def reconcile_lanes(feed: BoardFeed, store: HistoryStore) -> None:
    """Once `feed` has read what the stream retained, record the lanes its tasks are in that the history lacks."""
    feed.ready.wait()
    try:
        if recorded := feed.reconcile_lanes(store.current_lanes()):
            logger.warning("StarPulse: reconciled the lane of %d tasks the history had missed", recorded)
    except Exception:  # the history is down; the next start goes again
        logger.exception("StarPulse: cannot reconcile the lanes")


def forwarding(source: str, method: str, raw: bytes, forwarder: Forwarder | None) -> tuple[int, dict[str, Any]]:
    """Read (`GET`) what `forwarder` would send next, or set (`PUT {"opt_in": bool}`) whether a person's name may leave,
    for a browser at `source`: the HTTP status and JSON body, the forwarder's status or the refusal.

    An instance with no `[forward]` block has no forwarder: a read answers `{"configured": false}` so the page can say
    so, and a write is a 404. The opt-in is the file the forwarder reads before every batch, so a PUT takes effect at
    the next send.
    """
    if not _on_lan(source):
        return 403, {"error": "Forwarding answers only loopback and private network (RFC 1918) browsers"}
    if forwarder is None:
        if method == "PUT":
            return 404, {"error": "this instance forwards nothing: it has no [forward] block"}
        return 200, {"configured": False}
    if method == "PUT":
        try:
            opt_in = json.loads(raw)["opt_in"]
        except ValueError, TypeError, KeyError:
            opt_in = None
        if not isinstance(opt_in, bool):
            return 400, {"error": 'forwarding takes {"opt_in": true} or {"opt_in": false}'}
        forwarder.opt_in.set(opt_in)
    return 200, {"configured": True, **forwarder.status()}


def autopilot(source: str, method: str, raw: bytes, runtime: Runtime | None) -> tuple[int, dict[str, Any]]:
    """Read (`GET`) whether the autopilot admits tasks and each capacity dimension's use against its limit, or set
    (`PUT {"enabled": bool}`) whether it admits, for a browser at `source`: the HTTP status and JSON body.

    The switch is the file the autopilot reads, so a PUT takes effect at the next admission and survives a restart. A
    read answers any address, as every read does; a write answers only loopback and RFC 1918.
    """
    if runtime is None:
        return 404, {"error": "this instance runs no autopilot"}
    if method == "PUT":
        if not _on_lan(source):
            return 403, {"error": "The autopilot switch answers only loopback and private network (RFC 1918) browsers"}
        try:
            enabled = json.loads(raw)["enabled"]
        except ValueError, TypeError, KeyError:
            enabled = None
        if not isinstance(enabled, bool):
            return 400, {"error": 'the autopilot takes {"enabled": true} or {"enabled": false}'}
        runtime.set_enabled(enabled)
    return 200, runtime.status()
