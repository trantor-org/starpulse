"""Serve StarPulse: every lifecycle machine, the tasks in each, and the workflows of each runs adapter instance.

    .venv/bin/python -m starpulse.server [--port 8766] [--hours 6] [--config starpulse.toml]

GET /              the page, built by `pnpm --filter flow-view build` into static/: one view
                   that drills Board → Board state → machine, or Board → workflow. It holds one
                   /api/events connection and nothing else
GET /board, /flow/<name>, /runs
                   the same page; it opens the level that draws that graph, then rewrites the address to /
GET /?demo         the page driven by synthetic agents, for a look without live data
GET /api/events    server-sent events: a `snapshot` on connect ({graphs, dags, flows: [{name,
                   machine, agents}], pulls, settled, error, now}: every machine with its tasks, the
                   workflow declarations and the workflows, each named `<instance>/<workflow>`), then
                   a `task` delta ({id, agent, settled}) per Board task change, a `move` delta ({flow, id, agent}) per task a machine placed, a
                   `dags` delta ({dags, error}) per runs change, a `pulls` delta ({pulls}) per
                   change to a task's pull requests and a `claim` delta ({task, reason, at}) per
                   refused agent claim the board adapter reports, with a `: ping` comment every 15 s.
                   `pulls` maps each open task that cites a pull request to [{number, url, checks
                   (pass, failing, pending, none), merged, threads (unresolved), stale}], read from
                   GitHub through `gh` once a minute and held between reads; a failed read keeps the
                   last value with `stale` true.
                   Everything is held in memory: the Board from the configured board adapter, other machines' tasks
                   from machine:events, each instance's workflows from its adapter (`pushed/`: runs:events)
GET /api/snapshot  the document /api/events sends on connect, as one response, for `starpulse snapshot|board|task`
GET /api/history?task=TASK-N[&flow=NAME]
                   {task, path}: the task's Board lane changes as [{at, from, to}], oldest first (`at`
                   epoch seconds). With `flow`, {task, flow, path, steps}: its events on that lifecycle
                   machine as [{at, event, state}] in order, `steps` their count. A task never seen has an empty path; no `task` is 400
                   and an unknown `flow` 404. The machine events are copied from their stream as they
                   arrive into the history database (`database_url`, else starpulse-history.sqlite beside
                   the config), so the path outlives the stream's trim, unless the board adapter keeps
                   its own history. A trim past entries the copy never read is recorded as a gap
GET /api/analytics/health[?hours=N][&stuck_hours=N]
                   the Board's flow health from the history's lane changes (`analytics.board_health`): `states`
                   (each with `wip` now and, for a state that is not final, the `visits`, `mean_s` and `max_s` of
                   its stays over the last `hours`, default 168, `open` of them still going and counted to now),
                   `throughput` {count, per_day} into a final state, `stuck` (tasks in a middle state for
                   `stuck_hours` or longer, default 24, each `counted_to_now`) and `warnings` (the history's
                   recorded gaps). A `hours` or `stuck_hours` that is no positive number is 400; a history that
                   does not keep lane changes for every task is 501
GET /api/harnesses  {tiers, harnesses} from the config's `harnesses_file`; both empty with no file
POST /api/run/<instance>/<workflow>
                   start a run-safe workflow through its instance's optional `start`: {runId}, or {error}
                   with 403 for a source outside loopback and RFC 1918, 404 when the instance has no adapter
                   that can start a run or the workflow is not in its `run_safe`, 502 when the adapter's start
                   fails. A GET answers 405
POST /api/move     {task, to[, actor]}: set a Board task's status through the board adapter's writer, as `actor`
                   (`operator`, the page's identity, when absent). An actor outside the event's declared writers
                   is refused 409 before the writer is asked; a board with no writer answers 501
GET /api/task/<id> {task, record}: every editable field of a task from the board's `read`, which the snapshot's
                   entry does not carry; 404 when the board cannot read or the task is not on it
POST /api/edit     {task, base, changes, comment}: one write of every change through the board's `edit`. 409 with the
                   stale fields and their current values when any changed field no longer equals its `base`, or with
                   the writer's refusal and its skill; 403 outside loopback and RFC 1918. A GET answers 405
POST /api/archive  {task, reason}: archive a task from any lane through the board's `archive`; refusals as for an edit
POST /api/tasks    {title}: create a task in the board's first lane through the board's `create`, and answer 201 {task}
                   with its id; 400 for a missing, blank or over-long title, 403 outside loopback and RFC 1918, 404 when the board
                   does not create (the snapshot's `capabilities.create` says which). A GET answers 405
POST /api/start    {task, assignee}: start a task's session at `session_start_url` (see Start in the README)
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import queue
import shutil
import threading
import time
from collections.abc import Callable, Collection, Mapping
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from starpulse import analytics, run_events
from starpulse import events as machine_events
from starpulse.board import (
    AssigneeWriter,
    Board,
    MoveWriter,
    TaskArchiver,
    TaskCreator,
    TaskEditor,
    TaskReader,
    Written,
)
from starpulse.board import load as load_board
from starpulse.board_feed import BoardFeed, follow
from starpulse.config import Config, ConfigError, RunsInstance, discover, load, runs_adapter
from starpulse.contracts import Move, StartFailedError
from starpulse.event_log import EventLog
from starpulse.harnesses import Harnesses
from starpulse.history import HealthHistory, History, HistoryStore, database_url, record_machine_events
from starpulse.machine_tasks import MachineTasks
from starpulse.pull_requests import PullRequests
from starpulse.push_runs import PUSHED_INSTANCE, PushRuns
from starpulse.session_start import starter
from starpulse.settings import SETTINGS_FILE, HistoryWindow
from starpulse.snapshot import qualifier

_HERE = Path(__file__).parent
#: The Vite build of web/; it holds nothing but the page, so all of it is served.
_STATIC = _HERE / "static"
#: The page's one address and the retired per-graph ones, which the page redirects to their level.
_PAGES = {"/", "/board", "/runs"}
#: Seconds an idle event stream waits before a keep-alive comment, which is how a closed page is noticed.
_PING_S = 15.0
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
_RUN = "/api/run/"
_MOVE = "/api/move"
#: Who a move is made by when the request names no actor: the page, which acts for the operator.
OPERATOR = "operator"
_START = "/api/start"
_WINDOW = "/api/history-window"
_TASK = "/api/task/"
_EDIT = "/api/edit"
_ARCHIVE = "/api/archive"
_TASKS = "/api/tasks"
#: The longest title a create accepts; a title is one line on a card, not a description.
_TITLE_MAX = 300
#: Saves hold this from reading a task's current record to writing, so two browsers saving one task cannot both pass the stale check.
_EDIT_LOCK = threading.Lock()
#: The lanes Start session moves a task out of: the spec's start question, never Review's send-back.
_STARTABLE = frozenset({"ready", "waiting", "needs_attention"})


def _on_lan(source: str) -> bool:
    return any(ipaddress.ip_address(source) in net for net in _LAN)


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
    except ValueError, TypeError, KeyError:
        task = base = changes = comment = None
    if not (
        isinstance(task, str) and isinstance(base, dict) and isinstance(changes, dict) and changes
    ) or not isinstance(comment, str):
        return 400, {
            "error": 'an edit needs {"task": "TASK-N", "base": {...}, "changes": {...}, "comment": "<optional>"}'
        }
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
        written = edit(task, todo, comment)
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
    except ValueError, TypeError, KeyError:
        task = reason = None
    if not isinstance(task, str) or not isinstance(reason, str):
        return 400, {"error": 'an archive needs {"task": "TASK-N", "reason": "<optional text>"}'}
    if archive is None:
        return 404, {"error": "this board does not archive tasks"}
    if feed.task(task) is None:
        return 404, {"error": f"{task} is not on the board"}
    written = archive(task, reason)
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 200, {"task": task}


def create_task(source: str, raw: bytes, create: TaskCreator | None) -> tuple[int, dict[str, Any]]:
    """Create the task `raw` names in the board's first lane through `create`, for a browser at `source`: the HTTP
    status and JSON body, which holds the new task's id.

    The card appears in its column when the board adapter next reports the task, not on this answer.
    """
    if not _on_lan(source):
        return 403, {"error": "Creating a task answers only loopback and private network (RFC 1918) browsers"}
    try:
        title = json.loads(raw)["title"]
    except ValueError, TypeError, KeyError:
        title = None
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > _TITLE_MAX:
        return 400, {"error": f'a create needs {{"title": "<1 to {_TITLE_MAX} characters>"}}'}
    if create is None:
        return 404, {"error": "this board does not create tasks"}
    written = create(title.strip())
    if not written.ok:
        return 409, {"error": written.output, "skill": written.skill}
    return 201, {"task": written.output}


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
    except ValueError, TypeError, KeyError:
        task = assignee = None
    if not isinstance(task, str) or not isinstance(assignee, str):
        return 400, {"error": 'a start needs {"task": "TASK-N", "assignee": "@agent-<tier>-<effort>"}'}
    if start_session is None:
        return 404, {"error": "no session-start service is configured (session_start_url)"}
    if (agent := feed.task(task)) is None:
        return 404, {"error": f"{task} is not on the board"}
    if agent["state"] not in _STARTABLE:
        return 409, {
            "error": f"{task} is in {agent['state']}: a session starts only a ready, waiting or needs_attention task"
        }
    at = clock()
    if assignee != agent["model"] and not (written := assign(task, assignee)).ok:
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


def _error(message: str) -> bytes:
    return json.dumps({"error": message}).encode()


def history_response(history: History, query: dict[str, list[str]], flows: Collection[str]) -> tuple[bytes, int]:
    """The body and status for `/api/history`: a task's lane path, or with `flow` its path on that machine.

    `flows` are the machines the page draws."""
    task, flow = (query.get(key, [""])[0] for key in ("task", "flow"))
    if not task:
        return _error("history needs ?task=TASK-N"), 400
    if flow and flow not in flows:
        return _error(f"unknown flow {flow}"), 404
    body: dict[str, Any] = {"task": task}
    if flow:
        body |= {"flow": flow}
        body["path"], body["steps"] = history.machine_path(task, flow)
    else:
        body["path"] = history.lane_path(task)
    return json.dumps(body).encode(), 200


#: `/api/analytics/health`'s defaults: the window it counts over, and how long a stay in one state makes a task stuck.
_HEALTH_HOURS = 168.0
_STUCK_HOURS = 24.0


def _hours(query: dict[str, list[str]], key: str, default: float) -> float | None:
    """The positive, finite number of hours `key` gives, `default` when absent; None for anything else."""
    try:
        hours = float(query[key][0]) if key in query else default
    except ValueError:
        return None
    return hours if 0 < hours < float("inf") else None


def health_response(
    history: History, query: dict[str, list[str]], machines: Mapping[str, dict], now: float
) -> tuple[bytes, int]:
    """The body and status for `/api/analytics/health`: the Board's flow health over the last `hours` as of `now`."""
    window = _hours(query, "hours", _HEALTH_HOURS)
    stuck = _hours(query, "stuck_hours", _STUCK_HOURS)
    if window is None or stuck is None:
        return _error("hours and stuck_hours must each be a positive number"), 400
    if not isinstance(history, HealthHistory):
        return _error("this history does not keep every task's lane changes, so it cannot report flow health"), 501
    health = analytics.board_health(
        machines["board"], history.lane_rows(), history.gaps(), now=now, window_s=window * 3600, stuck_s=stuck * 3600
    )
    return json.dumps(health).encode(), 200


class _ApiHandler(SimpleHTTPRequestHandler):
    """The run endpoint and the JSON answer every API route sends; the page's routes subclass it."""

    starts: Mapping[str, Callable[[str], str]]
    run_safe: Collection[str]
    feed: BoardFeed
    window: HistoryWindow
    writer: MoveWriter
    assign: AssigneeWriter
    start_session: Callable[[str], str] | None
    read: TaskReader | None
    edit: TaskEditor | None
    archive: TaskArchiver | None
    create: TaskCreator | None

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith(_RUN) or path in {_MOVE, _START, _EDIT, _ARCHIVE, _TASKS}:
            self.send_response(405)
            self.send_header("Allow", "POST")  # pragma: no mutate: names are case-insensitive
            self.end_headers()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path in {_MOVE, _START, _EDIT, _ARCHIVE, _TASKS}:
            declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
            raw = self.rfile.read(int(declared or 0))
            if path == _MOVE:
                status, body = move_task(self.client_address[0], raw, self.feed, self.writer)
            elif path == _EDIT:
                status, body = edit_task(self.client_address[0], raw, self.feed, self.read, self.edit)
            elif path == _ARCHIVE:
                status, body = archive_task(self.client_address[0], raw, self.feed, self.archive)
            elif path == _TASKS:
                status, body = create_task(self.client_address[0], raw, self.create)
            else:
                status, body = start_task(self.client_address[0], raw, self.feed, self.assign, self.start_session)
        elif path.startswith(_RUN):
            status, body = run_dag(self.client_address[0], unquote(path.removeprefix(_RUN)), self.starts, self.run_safe)
        else:
            self.send_error(404)
            return
        self._send(json.dumps(body).encode(), status)

    def do_PUT(self) -> None:
        self._window("PUT")

    def do_DELETE(self) -> None:
        self._window("DELETE")

    def _window(self, method: str) -> None:
        """Answer the history window's route for `method`; no other path takes a PUT or DELETE."""
        if urlsplit(self.path).path != _WINDOW:
            self.send_error(404)
            return
        declared = self.headers.get("Content-Length")  # pragma: no mutate: header names are case-insensitive
        status, body = history_window(self.client_address[0], method, self.rfile.read(int(declared or 0)), self.window)
        self._send(json.dumps(body).encode(), status)

    def _send(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def _no_writer(task: str, status: str, actor: str = OPERATOR) -> Written:
    return Written(False, "no board writer is configured", unavailable=True)


def _handler(
    feed: BoardFeed,
    static: Path,
    starts: Mapping[str, Callable[[str], str]],
    run_safe: Collection[str],
    history: History,
    window: HistoryWindow,
    writer: MoveWriter = _no_writer,
    harnesses: Harnesses | None = None,
    assign: AssigneeWriter = _no_writer,
    start_session: Callable[[str], str] | None = None,
    read: TaskReader | None = None,
    edit: TaskEditor | None = None,
    archive: TaskArchiver | None = None,
    create: TaskCreator | None = None,
    clock: Callable[[], float] = time.time,
) -> type[SimpleHTTPRequestHandler]:
    harnesses_body = json.dumps((harnesses or Harnesses((), {})).as_json()).encode()
    flows = feed.machines.keys()

    class Handler(_ApiHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.starts = starts  # set first: the base __init__ handles the request
            self.run_safe = run_safe
            self.feed = feed
            self.window = window
            self.writer = writer
            self.assign = assign
            self.start_session = start_session
            self.read = read
            self.edit = edit
            self.archive = archive
            self.create = create
            super().__init__(*args, directory=str(static), **kwargs)  # pragma: no mutate: the server passes no kwargs

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/api/events":
                self._stream_events()
            elif url.path == "/api/snapshot":
                self._send(json.dumps(feed.snapshot()).encode())
            elif url.path == "/api/history":
                self._send(*history_response(history, parse_qs(url.query), flows))
            elif url.path == "/api/analytics/health":
                self._send(*health_response(history, parse_qs(url.query), feed.machines, clock()))
            elif url.path.startswith(_TASK):
                status, body = task_record(feed, read, unquote(url.path.removeprefix(_TASK)))
                self._send(json.dumps(body).encode(), status)
            elif url.path == "/api/harnesses":
                self._send(harnesses_body)
            elif url.path == _WINDOW:
                self._window("GET")  # pragma: no mutate: any method but PUT and DELETE reads the window
            elif url.path in _PAGES or url.path.startswith("/flow/") and url.path[6:] in flows - {"board"}:
                self.path = "/index.html"
                super().do_GET()
            else:
                super().do_GET()

        def list_directory(self, path: str | os.PathLike[str]) -> None:
            self.send_error(404)

        def _stream_events(self) -> None:
            """Hold the connection open: the Board's snapshot, then each change as it happens."""
            body, changes = feed.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")  # pragma: no mutate: names are case-insensitive
                self.send_header("Cache-Control", "no-store")  # pragma: no mutate: names are case-insensitive
                self.end_headers()
                self._event("snapshot", body)
                while True:
                    try:
                        self._event(*changes.get(timeout=_PING_S))
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")  # a closed page fails this write, which ends the stream
                        self.wfile.flush()
            except OSError:
                pass
            finally:
                feed.unsubscribe(changes)

        def _event(self, name: str, data: dict) -> None:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def _config(parser: argparse.ArgumentParser, path: Path | None) -> Config:
    """The config in `path`, else `starpulse.toml` beside where the view runs, else the defaults."""
    path = discover(path)
    try:
        return load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")


def _adapter(parser: argparse.ArgumentParser, instance: RunsInstance) -> ModuleType:
    """The runs adapter module of `instance`: `start(url)` gives its start capability or None, `follow(url, sink, log)` reads its workflows from the event log and the instance."""
    try:
        return runs_adapter(instance.type)
    except ConfigError as exc:
        parser.exit(1, f"runs instance {instance.name}: {exc}\n")


def assemble(config: Config, base: Path, window_s: float | None, run_safe: Collection[str]) -> tuple[Board, BoardFeed]:
    """The board the config's `[board]` adapter builds, and the feed that draws it; `base` is the config's directory.

    A task whose latest move on a machine is older than `window_s` seconds (None: never) is not drawn there, and Run
    now is drawn on the `run_safe` workflows.
    """
    board = load_board(config.board_type, config.board, base)
    domains = config.qualified_domains()
    qualify = qualifier(domains)
    feed = BoardFeed(
        window_s,
        board.keys,
        config.tracker_url,
        machines=board.machines(qualify, [name for names in domains.values() for name in names]),
        domains=domains,
        run_safe=run_safe,
        cues=board.cues(qualify),
        source=board.source,
        capabilities={
            "edit": board.edit is not None,
            "archive": board.archive is not None,
            "create": board.create is not None,
        },
        hint=found_backlog(config, base),
    )
    return board, feed


def found_backlog(config: Config, base: Path) -> str | None:
    """The line that names a Backlog.md project beside `base` and how to switch to it, when the config names no board.

    The default board is StarPulse's own; a project that already has a `backlog/` is told, not adopted.
    """
    if "type" in config.board or not (project := base / "backlog" / "config.yml").is_file():
        return None
    return (
        f"Found a Backlog.md project at {project}; StarPulse is showing its own board. "
        'To show that project instead, add [board] type = "upstream_backlog" to your starpulse.toml.'
    )


def announce(port: int, hint: str | None) -> None:
    """Say on the terminal where the view is, and the Backlog.md project it found when it did."""
    print(f"StarPulse on :{port}", flush=True)
    if hint:
        print(hint, flush=True)


def history_store(config: Config, base: Path, board: Board, machines: Mapping[str, dict]) -> History:
    """The board's own history when it keeps one, else StarPulse's store at `database_url` or beside the config.

    The store is opened either way, so every StarPulse table, the event log's included, is on that database.
    """
    store = HistoryStore(database_url(config.database_url, base), machines)
    return kept if (kept := board.history(machines)) is not None else store


def main(argv: list[str] | None = None) -> None:  # pragma: no mutate block — serve_forever process boundary
    parser = argparse.ArgumentParser(prog="starpulse serve", description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--hours",
        type=float,
        default=6.0,
        help="how far back a task's latest move on a machine counts; Admin's override replaces it",
    )
    parser.add_argument("--config", type=Path, help="the TOML config file; default starpulse.toml when it exists")
    args = parser.parse_args(argv)
    config = _config(parser, args.config)
    base = args.config.parent if args.config else Path.cwd()
    if not (_STATIC / "index.html").is_file():
        parser.exit(1, f"{_STATIC} has no build; run `pnpm --filter flow-view build` first\n")
    adapters = [(instance, _adapter(parser, instance)) for instance in config.runs]
    starts = {instance.name: start for instance, adapter in adapters if (start := adapter.start(instance.url))}
    # Run now is drawn only for an instance whose adapter can start a run, and only on its run-safe workflows.
    run_safe = [name for name in config.qualified_run_safe() if name.partition("/")[0] in starts]
    try:
        board, feed = assemble(config, base, args.hours * 3600, run_safe)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    # Every reader keeps its own cursor over the one event log, so a second copy on another port sees every entry too.
    # The declared --hours is the default; an override Admin wrote beside the config replaces it from the first snapshot.
    url = database_url(config.database_url, base)
    log = EventLog(url)
    window = HistoryWindow(feed, args.hours, base / SETTINGS_FILE)
    board.start(feed, f"flow-view-{args.port}", log)
    tasks = MachineTasks(feed, board.keys)
    follow(tasks, log, machine_events.STREAM, tasks.handle_entry)
    if shutil.which("gh"):  # without the GitHub CLI there is no source, and a task simply carries no PR state
        threading.Thread(target=PullRequests(feed).run_forever, name="pull-requests", daemon=True).start()
    for instance, adapter in adapters:
        adapter.follow(instance.url, feed.runs(instance.name), log)
    history = history_store(config, base, board, feed.machines)
    if isinstance(history, HistoryStore):
        threading.Thread(
            target=record_machine_events, args=(history, log, threading.Event()), name="machine-history", daemon=True
        ).start()
    # The learned step graphs persist only in StarPulse's own store.
    pushed = PushRuns(feed.runs(PUSHED_INSTANCE), history if isinstance(history, HistoryStore) else None)
    follow(pushed, log, run_events.STREAM, pushed.handle_entry)
    announce(args.port, feed.snapshot()["hint"])
    handler = _handler(
        feed,
        _STATIC,
        starts,
        run_safe,
        history,
        window,
        board.writer or _no_writer,
        config.harnesses,
        board.assign or _no_writer,
        starter(config.session_start_url),
        board.read,
        board.edit,
        board.archive,
        board.create,
    )
    ThreadingHTTPServer(("0.0.0.0", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
