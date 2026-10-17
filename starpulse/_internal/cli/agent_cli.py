"""`starpulse snapshot|board|task|machine|runs|watch|analytics|doctor|skills|help --agent`: the verbs an agent drives a running server with.

    starpulse board --milestone launch --label api
    starpulse task show PROJ-45
    starpulse task moves PROJ-45
    starpulse task move PROJ-45 review
    starpulse task claim PROJ-45 --session s-1
    starpulse task park PROJ-45 --until-task PROJ-40 --comment "needs the API"
    starpulse task review PROJ-45 --ref https://example.test/pull/9 --summary "Shipped"
    starpulse task trace PROJ-45 --flow in-progress
    starpulse task create "Rotate the secret" --priority high --label ops --ac "It rotates"
    starpulse task edit PROJ-45 --title "Rotate the signing secret" --label ops --label security
    starpulse task assign PROJ-45 @agent-standard-high
    starpulse task archive PROJ-45 --reason "superseded"
    starpulse task verdict PROJ-45 live pass --evidence "up=1"
    starpulse task miss PROJ-45 live --title "Repair live" --evidence "up=0"
    starpulse task restore PROJ-45
    starpulse task retire PROJ-45
    starpulse task retired PROJ-45
    starpulse task import-retired "retired/PROJ-3 - Old.md"
    starpulse task complete PROJ-45
    starpulse task checkpoint-ac PROJ-45 2 "pytest exits 0"
    starpulse machine show in-progress
    starpulse milestone list
    starpulse milestone show m-106
    starpulse milestone add "Launch" --outcome "Shipped" --spec "doc-1 - spec" --adr docs/adr/a.md
    starpulse milestone edit m-106 --outcome "Shipped and measured"
    starpulse milestone archive m-106
    starpulse doc list
    starpulse doc show doc-116
    starpulse doc create "Plan" --type specification --folder specs --body "# Plan"
    starpulse doc update doc-116 --body "# Plan, revised"
    starpulse doc archive doc-116
    starpulse doc restore doc-116 --folder specs
    starpulse runs list
    starpulse runs start prod/nightly
    starpulse watch --machine in-progress --task PROJ-45
    starpulse analytics health --hours 72
    starpulse analytics level --hours 48
    starpulse analytics trajectories --hours 48
    starpulse analytics gates --task PROJ-45
    starpulse analytics forecast --task PROJ-45
    starpulse analytics what-if --from review --to in_progress --p 0.1
    starpulse analytics transitions --hours 168
    starpulse analytics cells --hours 720
    starpulse analytics graph --hours 168
    starpulse analytics stages --hours 168
    starpulse analytics diff --hours 168
    starpulse doctor
    starpulse skills install --claude --codex
    starpulse help --agent

Every verb writes one JSON document to stdout, an error as `{"error": "...", "code": "..."}`, and nothing to stderr.
Every task write (`move`, `create`, `edit`, `assign`, `archive`, `checkpoint-ac`) is made as the actor `agent`, naming its
session and harness when `--session` and `--harness`, or `STARPULSE_SESSION` and `STARPULSE_HARNESS`, give them: the change's
lane entry records both, a create stamps `created_by: <harness>:<session>`, a claim (a move to `in_progress`) records the
session as the task's holder, and the board writer may answer with `advice`. A move the board machine declares for the operator alone, or that the
board's guard refuses, is `{"ok": false, "reason": "...", "skill": "..."}`, the verdict, and exit 1.
`task claim` moves a task to In Progress holding the session (an opaque string) and is refused while another session
holds it or the session holds another In Progress task; `task park` takes exactly one of `--until-task`, `--until` and
`--operator` and picks the lane from it (`waiting`, or `needs_attention` for the operator); `task review` moves to Review
with `--ref` evidence and the board's rules judge the record. Each answers like `task move`: a refusal is `ok: false`
with its reason and skill, exit 1, and nothing is written.
The exit code is 0 for success (for `doctor`, every check passing), 1 for a refused or invalid request, a refused
move or a failed `doctor` check, 2 for a usage error, 3 when the server (or what the
verb needs of it) is unavailable and 4 for something not found. The server is `--server`, else `STARPULSE_URL`, else
`http://localhost:8766`; a verb reads it per call and keeps nothing. `STARPULSE_TOKEN`, when set, is sent as a bearer
token on every request: a hub's reader token (`reader_token_env`), so an agent reads a hub without a browser sign-in.
`starpulse help --agent` prints the manifest of
verbs, generated from the parser below, so a verb added here is listed with its arguments, output keys and exit codes.
`watch` is the one verb that writes more than one document: it holds the server's event stream open and writes one JSON
line, `{"event": "task|move|pulls|claim|dags", "data": {...}}`, per change that `--machine` and `--task` leave in, until
it is interrupted (exit 0) or the server ends the stream (an error line, exit 3). `runs start` calls the server's Run
now path, so its LAN and `run_safe` guards apply to the agent as they do to the page.
`task create`, `task edit` and `task assign` write a task through the server's create and edit routes, as the Kanban page
does. `task edit` sends every field given in one write, which the server refuses whole (exit 1) when any field it
changes is no longer the value the edit was based on: that value is read from the task at the call, or is `--base`, the
JSON object of values the caller read earlier. A `--label`, `--dependency`, `--reference`, `--documentation` or
`--modified-file` given at all replaces that whole list, and a blank value clears a field. `task assign` is an edit of
the assignee alone, reported as the `profile` field. A board that cannot create, read or edit tasks answers exit 3.
`task verdict` comments the verdict (`pass`, or `miss` with `--fix` naming the task filed for it) of a check the task's
`## Post-merge Checks` block declares, `--evidence` with it; a verdict is final, so a second, an undeclared check or a
malformed block is refused (exit 1). `task miss` files the fix task (`--title` and the `task create` detail flags) and
records the MISS verdict naming it in one call, refused part-way leaving neither.
`task archive` moves a task from any lane to the board's archive, recording `--reason` as a comment when given, and
`task restore` returns an archived task's file to the board's tasks, unchanged, refusing one whose number is open or whose
file name is taken (exit 1), and returns a retired task the same way;
`task retire` takes a finished task (Done, completed or archived) off the board into the server's history store, kept
byte-for-byte, refusing an open task or a number kept with other text (exit 1); `task retired` reads every retired task,
or the one named, each with its file name and text; `task import-retired` keeps each retired task file a client held in
the history store, accepting the same file again, so a run a refusal stopped (exit 1) can be given the same files again;
`task complete` moves a Done task to the board's completed tasks and refuses one that is not Done (exit 1);
`task checkpoint-ac` checks one Acceptance Criterion and records its evidence as the comment `Verified AC #N: <evidence>`
in one write, refusing a criterion the task lacks (exit 1) without writing. A board that cannot do one answers exit 3.
`milestone` reads and writes the board's milestone records (title, outcome, specs, ADRs, retro) through the server;
a board that keeps none answers exit 3. A `--spec` or `--adr` on `milestone edit` replaces that whole list.
`doc` reads and writes the board's doc records (title, type, dates, folder, body) the same way: `doc list` leaves the
bodies out, `doc show` returns one with its `body`, and a board that keeps no docs answers exit 3. `doc restore`
returns an archived doc's file, unchanged, to `--folder` under the docs (the docs folder itself by default), refusing a doc
that is open or a destination that exists (exit 1).
`skills` reads no server: it copies the bundled skills into the project or, with `--user`, the home directory.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

import yaml

from starpulse._internal.cli import demo, skill_install
from starpulse._internal.cli import doctor
from starpulse._internal.config.config import ConfigError, load
from starpulse._internal.board.view import AGENT, board_columns, board_flow, cold_agent, done_ids, task_view

#: serve's default `--port`, where a server runs unless the caller says otherwise.
DEFAULT_SERVER = "http://localhost:8766"
#: What each exit code means, as the manifest says it.
EXIT_CODES = {0: "ok", 1: "refused or invalid", 2: "usage", 3: "unavailable", 4: "not found"}
#: The exit code of each error `code`.
_ERROR_EXIT = {"refused": 1, "usage": 2, "unavailable": 3, "not_found": 4}

_SNAPSHOT_KEYS = (
    "graphs",
    "flows",
    "dags",
    "pools",
    "pulls",
    "mergeStrip",
    "mergePins",
    "machinePage",
    "machineStrip",
    "claims",
    "insights",
    "settled",
    "cold_done",
    "error",
    "cues",
    "domains",
    "boardUrl",
    "hint",
    "capabilities",
    "reading",
    "now",
)
_LEVEL_KEYS = (
    "now",
    "window_s",
    "history_s",
    "machine",
    "goal",
    "wip",
    "throughput",
    "time_in_state",
    "aging",
    "orbit",
    "sources",
)
_TRAJECTORY_KEYS = (
    "now",
    "window_s",
    "history_s",
    "machine",
    "goal",
    "ended",
    "variants",
    "norm",
    "outliers",
    "chain",
    "betweenness",
    "bottleneck",
    "loops",
    "runs",
)
_GATE_KEYS = ("now", "window_s", "history_s", "machine", "goal", "ended", "gates", "runs")
_FORECAST_KEYS = ("now", "window_s", "history_s", "machine", "goal", "ended", "forecast", "calibration")
_WHAT_IF_KEYS = (
    "now",
    "window_s",
    "history_s",
    "machine",
    "goal",
    "ended",
    "from",
    "to",
    "p",
    "was",
    "n",
    "start",
    "p_goal",
    "expected_days",
    "chain",
)
_HEALTH_KEYS = ("now", "window_s", "stuck_after_s", "states", "throughput", "stuck", "warnings")
_STEP_KEYS = ("now", "window_s", "steps")
_TRANSITION_KEYS = ("now", "window_s", "transitions")
_CELL_KEYS = ("now", "window_s", "cells")
_GRAPH_KEYS = ("now", "window_s", "graph")
_STAGE_KEYS = ("now", "window_s", "stages")
_DIFF_KEYS = ("now", "window_s", "diff")
_TASK_KEYS = (
    "id",
    "title",
    "lane",
    "assignee",
    "holder",
    "milestone",
    "type",
    "labels",
    "dependencies",
    "waiting_on",
    "criteria",
    "pause_reason",
    "prs",
    "moves",
    "description",
)
_MOVE_KEYS = ("ok", "task", "to", "reason", "skill", "advice")
_CLAIM_KEYS = ("ok", "task", "to", "holder", "reason", "skill")
_LIFECYCLE_KEYS = ("ok", "task", "to", "reason", "skill")
_MILESTONE_KEYS = ("id", "title", "outcome", "specs", "adrs", "retro", "description")
_DOC_KEYS = ("id", "title", "type", "created_date", "updated_date", "path", "body")
#: Seconds `watch` waits for the next byte: the server pings every 15, so a longer silence is a server that is gone.
_STREAM_TIMEOUT_S = 45.0

#: A verb answers with one document, or with the stream of documents `watch` writes as they arrive.
Verb = Callable[[argparse.Namespace, Mapping[str, str]], dict[str, Any] | Iterator[dict[str, Any]]]


class _AnyName(Mapping[str, Callable[..., Any]]):
    """Every guard or action name an adapter might register: a file alone cannot say which names it will."""

    def __getitem__(self, name: str) -> Callable[..., Any]:
        return lambda *args, **kwargs: True

    def __contains__(self, name: object) -> bool:
        return True

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


class CliError(Exception):
    """A request a verb cannot answer: `code` is one of `_ERROR_EXIT`, the message says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _Parser(argparse.ArgumentParser):
    """A parser whose usage errors are `CliError`s, so they reach stdout as JSON instead of stderr as text."""

    def error(self, message: str) -> NoReturn:
        raise CliError("usage", message)


class Server(str):
    """A server's address, which formats as the address, carrying the bearer token every request to it sends."""

    token: str

    def __new__(cls, address: str, token: str = "") -> Server:
        server = super().__new__(cls, address)
        server.token = token
        return server


def server_url(flag: str | None, environ: Mapping[str, str]) -> Server:
    """The server to read: the `--server` flag, else `STARPULSE_URL`, else the default, without a trailing slash, with
    `STARPULSE_TOKEN` as its bearer token: a hub's reader token, which reads what a signed-in viewer reads."""
    address = (flag or environ.get("STARPULSE_URL") or DEFAULT_SERVER).rstrip("/")
    return Server(address, environ.get("STARPULSE_TOKEN", ""))


def _auth(base: str) -> dict[str, str]:
    """The Authorization header `base` carries, if any."""
    return {"Authorization": f"Bearer {base.token}"} if isinstance(base, Server) and base.token else {}


def _get(base: str, path: str) -> tuple[int, Any]:
    """The status and JSON body the server at `base` answers `path` with; None for a body that is no JSON."""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{base}{path}", headers=_auth(base)),
            timeout=10.0,  # seconds the server may take to answer one read
        ) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, None
    except TimeoutError as exc:  # before OSError: a slow search is not an unreachable server
        if path.startswith("/api/search"):
            raise CliError("unavailable", f"slow search at {base}: timed out after 10s") from exc
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc


def _get_snapshot(base: str) -> dict[str, Any]:
    """The snapshot the server at `base` answers; JSON without every snapshot key is no StarPulse server."""
    path = "/api/snapshot"
    status, document = _get(base, f"{path}?view=full")
    if status != 200:
        raise CliError("unavailable", f"{base} answered {status} for {path}: is it a StarPulse server?")
    if not isinstance(document, dict) or not document.keys() >= set(_SNAPSHOT_KEYS):
        raise CliError("unavailable", f"{base} answered {path} with no StarPulse snapshot: is it a StarPulse server?")
    return document


def _snapshot(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return _get_snapshot(server_url(args.server, environ))


def _board(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = _snapshot(args, environ)
    states = board_flow(snapshot)["machine"]["states"]
    if args.state and args.state not in (ids := [s["id"] for s in states]):
        raise CliError("usage", f"unknown state {args.state}; the board has {', '.join(ids)}")

    def kept(agent: dict[str, Any]) -> bool:
        return (
            (not args.milestone or agent["milestone"] == args.milestone)
            and (not args.type or agent.get("type", "") == args.type)
            and (not args.label or args.label in agent["labels"])
            and (not args.assignee or agent["model"] == args.assignee)
            and (not args.holder or agent.get("holder", "") == args.holder)
        )

    board = board_columns(snapshot, kept, args.state)
    if args.milestone and snapshot.get("cold_done") and args.state in (None, "done"):
        done = done_ids(snapshot)
        column = next(column for column in board["columns"] if column["state"] == "done")
        bare = {"milestone": "", "labels": [], "dependencies": [], "prs": [], "moves": {}}
        cards = [bare | card for card in _cold_done(server_url(args.server, environ))]
        column["tasks"] += [task_view(card, snapshot, done) for card in cards if kept(card)]
    return board


def _cold_done(base: str) -> Iterator[dict[str, Any]]:
    """Every done task past its hot day as a board card, newest first; the snapshot lists them by id only."""
    before = ""
    while True:
        status, page = _get(base, f"/api/done?limit=100{before}")
        if status != 200:
            raise CliError("unavailable", f"{base} answered {status} for /api/done: cannot list the done tasks")
        yield from page["tasks"]
        if not page["more"]:
            return
        before = f"&before={page['tasks'][-1]['entered']}"


def _show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = _snapshot(args, environ)
    wanted = args.task.casefold()
    agents = {agent["id"].casefold(): agent for agent in board_flow(snapshot)["agents"]}
    if (agent := agents.get(wanted)) is None:
        cold = next((task for task in snapshot.get("cold_done", ()) if task.casefold() == wanted), None)
        if cold is not None:
            return _show_cold(server_url(args.server, environ), cold, snapshot)
        settled_id, settled = next(
            ((key, value) for key, value in snapshot["settled"].items() if key.casefold() == wanted), (None, None)
        )
        if settled is None:
            raise CliError("not_found", f"{args.task} is not on the board")
        # A settled task has left the lanes, and the snapshot keeps only where it settled.
        agent = {
            "id": settled_id,
            "title": "",
            "state": settled["state"],
            "model": "",
            "milestone": "",
            "labels": [],
            "dependencies": [],
            "prs": [],
            "moves": {},
            "description": "",
        }
    return {**task_view(agent, snapshot), "description": agent["description"]}


def _show_cold(base: str, task_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """A done task past its hot day, whole: the snapshot holds only its id, so its record is read from the board."""
    status, document = _get(base, f"/api/task/{urllib.parse.quote(task_id, safe='')}")
    if status != 200:
        raise CliError("unavailable", f"{base} answered {status} for the record of {task_id}")
    agent = cold_agent(task_id, document["record"])
    return {**task_view(agent, snapshot), "description": agent["description"]}


def _moves(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    shown = _show(args, environ)
    return {"task": shown["id"], "lane": shown["lane"], "moves": shown["moves"]}


def _writer_flags(sub: argparse.ArgumentParser) -> None:
    """Add the flags that name the session and harness a task write is made from."""
    sub.add_argument(
        "--session",
        default="",
        help="the session writing, recorded as the holder of a claimed task and on the change (else `STARPULSE_SESSION`)",
    )
    sub.add_argument(
        "--harness", default="", help="the harness of that session (`claude`, `cursor`), else `STARPULSE_HARNESS`"
    )


def _writer(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, str]:
    """Who a task write names as its writer: the agent, with the session and harness `--session` and `--harness` give,
    else `STARPULSE_SESSION` and `STARPULSE_HARNESS`; one neither gives is left out, and the server records it anonymous."""
    named = {
        "session": args.session or environ.get("STARPULSE_SESSION", ""),
        "harness": args.harness or environ.get("STARPULSE_HARNESS", ""),
    }
    return {"actor": AGENT, **{key: value for key, value in named.items() if value}}


def _move(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Move the task as the agent: the server's verdict, or an error when no board writer can answer."""
    base = server_url(args.server, environ)
    body = {"task": args.task, "to": args.to, **_writer(args, environ)}
    status, reply = _post(base, "/api/move", body)
    message = reply.get("error") or f"{base} answered {status} for /api/move"
    if status == 200:
        return {
            "ok": True,
            "task": args.task,
            "to": args.to,
            "reason": "",
            "skill": "",
            "advice": reply.get("advice", ""),
        }
    if status == 409:
        return {
            "ok": False,
            "task": args.task,
            "to": args.to,
            "reason": message,
            "skill": reply.get("skill", ""),
            "advice": "",
        }
    if status == 404:
        raise CliError("not_found", message)
    if status in (400, 403):
        raise CliError("refused", message)
    raise CliError("unavailable", f"{base}: {message}")


def _lifecycle(
    args: argparse.Namespace, environ: Mapping[str, str], verb: str, fields: dict[str, Any]
) -> dict[str, Any]:
    """Post the lifecycle verb `verb` (`claim`, `park`, `review`) for the task as the agent: the server's answer, with a
    refusal as `ok: false` and its reason and skill, or an error when no board writer can answer."""
    base, path = server_url(args.server, environ), f"/api/{verb}"
    status, reply = _post(base, path, {"task": args.task, **fields, **_writer(args, environ)})
    message = reply.get("error") or f"{base} answered {status} for {path}"
    if status == 200:
        return {
            "ok": True,
            "task": args.task,
            "to": reply.get("to", ""),
            "holder": reply.get("holder", ""),
            "reason": "",
            "skill": "",
        }
    if status == 409:
        return {
            "ok": False,
            "task": args.task,
            "to": "",
            "holder": "",
            "reason": message,
            "skill": reply.get("skill", ""),
        }
    if status == 404 and any(text in message for text in _TASK_MISSING):
        raise CliError("not_found", message)
    if status in (400, 403):
        raise CliError("refused", message)
    raise CliError("unavailable", f"{base}: {message}")


def _kept(output: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """`output` without the keys a verb does not report."""
    return {key: output[key] for key in keys}


def _task_claim(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Claim the task for the session: it moves to In Progress with that session as holder, refused when another holds it."""
    return _kept(_lifecycle(args, environ, "claim", {}), _CLAIM_KEYS)


def _criterion(text: str) -> dict[str, Any]:
    """The `--until` criterion `text` (YAML or JSON) names, refused when it is not a mapping."""
    try:
        criterion = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CliError("refused", f"--until is not YAML or JSON: {exc}") from exc
    if not isinstance(criterion, dict):
        raise CliError("refused", f"--until must be a mapping, got {text!r}")
    return criterion


def _task_park(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Park the task on one reason: `--until-task` and `--until` wait, `--operator` needs attention; the server picks the lane."""
    fields = {
        "untilTask": args.until_task,
        "until": [_criterion(text) for text in args.until],
        "operator": args.operator,
        "comment": args.comment,
    }
    given = {key: value for key, value in fields.items() if value}
    return _kept(_lifecycle(args, environ, "park", given), _LIFECYCLE_KEYS)


def _task_review(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Move the task to Review with `--ref` references and `--summary`: the configured rules judge the resulting record."""
    fields = {"references": args.ref, "summary": args.summary, "comment": args.comment}
    given = {key: value for key, value in fields.items() if value}
    return _kept(_lifecycle(args, environ, "review", given), _LIFECYCLE_KEYS)


def _post(base: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """The status and JSON object the server at `base` answers a POST of `body` to `path` with; {} for any other body."""
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **_auth(base)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=10.0,  # seconds the board writer or the runs adapter may take to answer
        ) as resp:
            return resp.status, _json_or_empty(resp)
    except urllib.error.HTTPError as exc:  # before OSError, which it subclasses
        return exc.code, _json_or_empty(exc)
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc


def _json_or_empty(resp: Any) -> dict[str, Any]:
    try:
        document = json.load(resp)
    except ValueError:
        return {}
    return document if isinstance(document, dict) else {}


#: What a task route's 404 says when the board has no such task, as opposed to a board that cannot read or write tasks.
_TASK_MISSING = ("is not on the board", "has no record to read")


def _record_call(
    base: str,
    path: str,
    status: int,
    reply: Any,
    *,
    ok: tuple[int, ...] = (200,),
    noun: str = "milestone",
    missing: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The JSON object a milestone, doc or task route answered with, or the `CliError` its status maps to."""
    document = reply if isinstance(reply, dict) else {}
    if status in ok and document:
        return document
    message = document.get("error") or f"{base} answered {status} for {path}: is it a StarPulse server?"
    if status == 404 and "error" in document:
        # The server gives both 404s as text only: a board that keeps no such records, else one that is not open.
        absent = (f"is not an open {noun}", *missing)
        raise CliError("not_found" if any(text in message for text in absent) else "unavailable", message)
    if status in (400, 403, 409):
        raise CliError("refused", message)
    raise CliError("unavailable", f"{base}: {message}")


#: Each `task edit` flag's destination and the record field it sets, in the order `changed` reports them.
_TASK_EDIT_FIELDS = {
    "title": "title",
    "type": "type",
    "priority": "priority",
    "milestone": "milestone",
    "label": "labels",
    "dependency": "dependencies",
    "reference": "references",
    "documentation": "documentation",
    "modified_file": "modifiedFiles",
    "description": "description",
    "plan": "plan",
    "notes": "notes",
    "final_summary": "finalSummary",
}
#: The checklists `task edit` changes: each record field's flag key (`--ac`, `--reword-ac`, ...) and the name a refusal gives it.
_CHECKLISTS = {"acceptanceCriteria": ("ac", "Acceptance Criteria"), "definitionOfDone": ("dod", "Definition of Done")}
#: A checklist's flag destinations, as `{}` stands for its key: add, reword, remove, check and uncheck.
_CHECKLIST_DESTS = ("{}", "reword_{}", "remove_{}", "check_{}", "uncheck_{}")


def _create_flags(sub: argparse.ArgumentParser) -> None:
    """Add the detail flags of a task a `create` or `miss` command files; the title is the caller's."""
    sub.add_argument("--description", help="the task's Description section")
    sub.add_argument("--priority", help="`high`, `medium` or `low`")
    sub.add_argument("--milestone", help="the milestone's id (`m-106`)")
    sub.add_argument("--assignee", help="who or which agent profile holds it (`@agent-standard-high`)")
    sub.add_argument("--label", action="append", help="a label; repeat for several")
    sub.add_argument("--dependency", action="append", help="a task it depends on; repeat for several")
    sub.add_argument("--ac", action="append", help="an Acceptance Criterion; repeat for several, in order")
    sub.add_argument("--status", help="the lane to open it in, else the board's first (`Waiting`)")
    sub.add_argument("--type", help="the task's type (`bug`)")
    sub.add_argument("--reference", action="append", help="a reference; repeat for several")
    sub.add_argument("--documentation", action="append", help="a documentation link; repeat for several")
    sub.add_argument("--dod", action="append", help="a Definition of Done item; repeat for several, in order")


def _created_task(args: argparse.Namespace) -> dict[str, Any]:
    """The title and details a `create` or `miss` command line names, each field only when given."""
    given = {
        "description": args.description,
        "priority": args.priority,
        "milestone": args.milestone,
        "assignee": args.assignee,
        "labels": args.label,
        "dependencies": args.dependency,
        "acceptanceCriteria": args.ac,
        "status": args.status,
        "type": args.type,
        "references": args.reference,
        "documentation": args.documentation,
        "definitionOfDone": args.dod,
    }
    return {"title": args.title, **{k: v for k, v in given.items() if v is not None}}


def _task_create(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/tasks"
    status, reply = _post(base, path, {**_created_task(args), **_writer(args, environ)})
    return {"task": _record_call(base, path, status, reply, ok=(201,))["task"]}


def _task_verdict(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/verdict"
    body = {"task": args.task, "check": args.check, "verdict": args.verdict, "evidence": args.evidence}
    if args.fix:
        body["fix"] = args.fix
    status, reply = _post(base, path, {**body, **_writer(args, environ)})
    judged = _record_call(base, path, status, reply, missing=_TASK_MISSING)
    return {key: judged[key] for key in ("task", "check", "verdict")}


def _task_miss(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/miss"
    body = {"task": args.task, "check": args.check, "fix": _created_task(args), "evidence": args.evidence}
    status, reply = _post(base, path, {**body, **_writer(args, environ)})
    return _record_call(base, path, status, reply, missing=_TASK_MISSING)


def _task_edit_call(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    changes: dict[str, Any],
    base_record: dict[str, Any] | None,
    comment: str = "",
) -> list[str]:
    """Send `changes` to `/api/edit` as one write and return the fields that changed.

    `base_record` is what the caller read the task as; without one the task is read now, so the edit is refused only
    for a field another writer changes between that read and this write.
    """
    base = server_url(args.server, environ)
    if base_record is None:
        current = _read_record(args, environ)
        base_record = {field: current.get(field) for field in changes}
    body = {"task": args.task, "base": base_record, "changes": changes, "comment": comment, **_writer(args, environ)}
    status, reply = _post(base, "/api/edit", body)
    return _record_call(base, "/api/edit", status, reply, missing=_TASK_MISSING)["changed"]


def _read_record(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The task `args.task` as the board's reader gives it."""
    base, path = server_url(args.server, environ), f"/api/task/{urllib.parse.quote(args.task, safe='')}"
    status, reply = _get(base, path)
    return _record_call(base, path, status, reply, missing=_TASK_MISSING)["record"]


def _checklist_flags(args: argparse.Namespace, key: str) -> tuple[list[Any], ...]:
    """The values given to a checklist's add, reword, remove, check and uncheck flags, each `[]` when not given."""
    return tuple(getattr(args, dest.format(key)) or [] for dest in _CHECKLIST_DESTS)


def _checklist_after(args: argparse.Namespace, field: str, items: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The checklist `field` after the flags given, or None when it has none.

    A flag names an item by the number the task shows before this edit. A removal sends the whole list without numbers, so
    the board writes it numbered from 1; any other edit sends the numbers, which the board keeps.
    """
    key, name = _CHECKLISTS[field]
    add, reword, remove, check, uncheck = _checklist_flags(args, key)
    if not (add or reword or remove or check or uncheck):
        return None
    reworded = {}
    for value in reword:
        number, colon, wording = value.partition(":")
        if not (colon and number.strip().isdigit()):
            raise CliError("usage", f"--reword-{key} takes N:TEXT, as 2:The new wording")
        reworded[int(number)] = wording
    present = {item["n"] for item in items}
    if absent := [number for number in (*reworded, *remove, *check, *uncheck) if number not in present]:
        raise CliError("refused", f"{args.task} has no {name} item #{absent[0]}")
    kept = [
        {
            "n": item["n"],
            "text": reworded.get(item["n"], item["text"]),
            "checked": (item["checked"] or item["n"] in check) and item["n"] not in uncheck,
        }
        for item in items
        if item["n"] not in remove
    ]
    after = [*kept, *({"text": text, "checked": False} for text in add)]
    return [{k: v for k, v in item.items() if k != "n"} for item in after] if remove else after


def _task_edit(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    changes = {
        field: getattr(args, flag) for flag, field in _TASK_EDIT_FIELDS.items() if getattr(args, flag) is not None
    }
    if args.append_notes:
        changes["appendNotes"] = "\n".join(args.append_notes)
    checklists = [field for field, (key, _) in _CHECKLISTS.items() if any(_checklist_flags(args, key))]
    if not changes and not checklists:
        flags = (
            *(f"--{flag.replace('_', '-')}" for flag in _TASK_EDIT_FIELDS),
            "--append-notes",
            *(
                f"--{dest.format(key).replace('_', '-')}"
                for key, _ in _CHECKLISTS.values()
                for dest in _CHECKLIST_DESTS
            ),
        )
        raise CliError("usage", f"name what to change: {', '.join(flags)}")
    base_record = None
    if args.base is not None:
        try:
            base_record = json.loads(args.base)
        except ValueError:
            base_record = None
        if not isinstance(base_record, dict):
            raise CliError("usage", '--base must be a JSON object of the values read, as {"title": "..."}')
    if checklists:
        record = _read_record(args, environ)  # the items are edited as read, so the same read is the edit's base
        for field in checklists:
            changes[field] = _checklist_after(args, field, record[field])
        read = {field: record.get(field) for field in changes if field != "appendNotes"}
        base_record = {**read, **(base_record or {})}
    return {"task": args.task, "changed": _task_edit_call(args, environ, changes, base_record, args.comment)}


def _task_assign(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    changed = _task_edit_call(args, environ, {"profile": args.assignee}, None)
    return {"task": args.task, "assignee": args.assignee, "changed": changed}


def _task_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/archive"
    status, reply = _post(base, path, {"task": args.task, "reason": args.reason, **_writer(args, environ)})
    return {"task": _record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def _task_restore(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/restore"
    status, reply = _post(base, path, {"task": args.task})
    return {"task": _record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def _task_retire(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/retire"
    status, reply = _post(base, path, {"task": args.task})
    return {"task": _record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def _task_retired(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base = server_url(args.server, environ)
    path = f"/api/retired?task={urllib.parse.quote(args.task, safe='')}" if args.task else "/api/retired"
    status, reply = _get(base, path)
    return {"tasks": _record_call(base, path, status, reply, noun="retired task")["tasks"]}


def _task_import_retired(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/retired/import"
    files = [Path(file) for file in args.files]
    if unreadable := [str(file) for file in files if not file.is_file()]:
        raise CliError("usage", f"no such file: {', '.join(unreadable)}")
    tasks = []
    for file in files:  # the bytes as kept: read_text would turn a CRLF file's line ends into LF
        status, reply = _post(base, path, {"name": file.name, "text": file.read_bytes().decode()})
        tasks.append(_record_call(base, path, status, reply, noun="retired task")["task"])
    return {"tasks": tasks}


def _task_complete(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/complete"
    status, reply = _post(base, path, {"task": args.task})
    return {"task": _record_call(base, path, status, reply, missing=_TASK_MISSING)["task"]}


def _task_checkpoint_ac(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    evidence = args.evidence.strip()
    if not evidence:
        raise CliError("usage", "evidence is required to check an Acceptance Criterion")
    criteria = _read_record(args, environ).get("acceptanceCriteria") or []
    if args.criterion not in {item["n"] for item in criteria}:
        raise CliError("refused", f"{args.task} has no Acceptance Criteria item #{args.criterion}")
    checked = [{**item, "checked": True} if item["n"] == args.criterion else item for item in criteria]
    changed = _task_edit_call(
        args,
        environ,
        {"acceptanceCriteria": checked},
        {"acceptanceCriteria": criteria},
        f"Verified AC #{args.criterion}: {evidence}",
    )
    return {"task": args.task, "criterion": args.criterion, "changed": changed}


def _milestone_list(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/milestones"
    status, reply = _get(base, path)
    return {"milestones": _record_call(base, path, status, reply)["milestones"]}


def _milestone_show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), f"/api/milestones/{urllib.parse.quote(args.milestone, safe='')}"
    status, reply = _get(base, path)
    return _record_call(base, path, status, reply)["milestone"]


def _milestone_add(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/milestones"
    body: dict[str, Any] = {"title": args.title}
    body.update(_milestone_fields(args))
    status, reply = _post(base, path, body)
    return {"milestone": _record_call(base, path, status, reply, ok=(201,))["milestone"]}


def _milestone_edit(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/milestones/edit"
    changes = {**({"title": args.title} if args.title is not None else {}), **_milestone_fields(args)}
    if not changes:
        raise CliError("usage", "name what to change: --title, --outcome, --spec, --adr or --retro")
    status, reply = _post(base, path, {"milestone": args.milestone, "changes": changes})
    document = _record_call(base, path, status, reply)
    return {"milestone": document["milestone"], "changed": document["changed"]}


def _milestone_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/milestones/archive"
    status, reply = _post(base, path, {"milestone": args.milestone})
    return {"milestone": _record_call(base, path, status, reply)["milestone"]}


def _doc_list(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/docs"
    status, reply = _get(base, path)
    return {"docs": _record_call(base, path, status, reply, noun="doc")["docs"]}


def _doc_show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), f"/api/docs/{urllib.parse.quote(args.doc, safe='')}"
    status, reply = _get(base, path)
    return _record_call(base, path, status, reply, noun="doc")["doc"]


def _doc_fields(args: argparse.Namespace) -> dict[str, Any]:
    """The detail fields (type, body) the caller gave."""
    return {field: value for field, value in {"type": args.type, "body": args.body}.items() if value is not None}


def _doc_create(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/docs"
    body = {"title": args.title, **_doc_fields(args), **({"folder": args.folder} if args.folder is not None else {})}
    status, reply = _post(base, path, body)
    return {"doc": _record_call(base, path, status, reply, ok=(201,), noun="doc")["doc"]}


def _doc_update(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/docs/edit"
    changes = {**({"title": args.title} if args.title is not None else {}), **_doc_fields(args)}
    if not changes:
        raise CliError("usage", "name what to change: --title, --type or --body")
    status, reply = _post(base, path, {"doc": args.doc, "changes": changes})
    document = _record_call(base, path, status, reply, noun="doc")
    return {"doc": document["doc"], "changed": document["changed"]}


def _doc_archive(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/docs/archive"
    status, reply = _post(base, path, {"doc": args.doc})
    return {"doc": _record_call(base, path, status, reply, noun="doc")["doc"]}


def _doc_restore(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base, path = server_url(args.server, environ), "/api/docs/restore"
    status, reply = _post(base, path, {"doc": args.doc, **({"folder": args.folder} if args.folder else {})})
    return {"doc": _record_call(base, path, status, reply, noun="doc")["doc"]}


def _search(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    base = server_url(args.server, environ)
    given = {"limit": args.limit, "label": args.label, "finished_within_days": args.finished_within_days}
    query = {"q": " ".join(args.query), **{key: value for key, value in given.items() if value is not None}}
    path = f"/api/search?{urllib.parse.urlencode(query, doseq=True)}"
    status, reply = _get(base, path)
    found = _record_call(base, path, status, reply, noun="search")
    return {"query": found["query"], "hits": found["hits"]}


def _milestone_fields(args: argparse.Namespace) -> dict[str, Any]:
    """The detail fields (outcome, specs, ADRs, retro) the caller gave; a list flag given at all replaces the list."""
    given = {"outcome": args.outcome, "specs": args.spec, "adrs": args.adr, "retro": args.retro}
    return {field: value for field, value in given.items() if value is not None}


def _trace(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The task's Board lane changes, or with `--flow` its events on that machine, both as the server's history has them."""
    base = server_url(args.server, environ)
    query = urllib.parse.urlencode({"task": args.task, **({"flow": args.flow} if args.flow else {})})
    path = f"/api/history?{query}"
    status, document = _get(base, path)
    if args.flow and status == 404 and isinstance(document, dict) and "error" in document:
        raise CliError("not_found", document["error"])
    if status != 200 or not isinstance(document, dict) or "path" not in document:
        raise CliError("unavailable", f"{base} answered {status} for {path}: is it a StarPulse server?")
    return {
        "task": document["task"],
        "flow": document.get("flow"),
        "path": document["path"],
        "steps": document.get("steps", len(document["path"])),
    }


def _machines(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    flows = _snapshot(args, environ)["flows"]
    return {
        "machines": [
            {"name": f["name"], "states": [s["id"] for s in f["machine"]["states"]], "tasks": len(f["agents"])}
            for f in flows
        ]
    }


def _machine(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """One machine's states with the live count and the tasks in each, and its transitions."""
    flows = {f["name"]: f for f in _snapshot(args, environ)["flows"]}
    if (flow := flows.get(args.name)) is None:
        raise CliError("not_found", f"{args.name} is not a machine; the server draws {', '.join(flows)}")
    machine = flow["machine"]
    tasks: dict[str, list[str]] = {state["id"]: [] for state in machine["states"]}
    for agent in flow["agents"]:
        tasks.setdefault(agent["state"], []).append(agent["id"])
    document = {
        "name": flow["name"],
        "states": [
            {**state, "count": len(tasks[state["id"]]), "tasks": tasks[state["id"]]} for state in machine["states"]
        ],
        "transitions": machine["transitions"],
        **{key: machine[key] for key in ("subflows", "launches", "writers") if key in machine},
    }
    if args.format == "dot":
        from starpulse._internal.machines.diagram import dot  # noqa: PLC0415 - import cost, paid on first use

        document |= {"format": "dot", "diagram": dot(flow["name"], machine)}
    return document


def _runs(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = _snapshot(args, environ)
    return {
        "runs": [
            {
                "workflow": dag["name"],
                "status": dag["status"],
                "raw": dag.get("raw"),
                "run_id": dag["runId"],
                "started_at": dag["startedAt"],
                "finished_at": dag["finishedAt"],
            }
            for dag in snapshot["dags"]
        ],
        "error": snapshot["error"],
    }


def _run_start(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Start a workflow through the server's Run now path: its run id, or why the server's guards refused it."""
    base = server_url(args.server, environ)
    if "/" not in args.workflow:
        raise CliError("usage", f"name the workflow as <instance>/<workflow>, as `runs list` shows it: {args.workflow}")
    path = f"/api/run/{urllib.parse.quote(args.workflow, safe='/')}"
    status, reply = _post(base, path, {})
    message = reply.get("error") or f"{base} answered {status} for {path}: is it a StarPulse server?"
    if status == 200 and "runId" in reply:
        return {"workflow": args.workflow, "run_id": reply["runId"]}
    if status == 403:
        raise CliError("refused", message)
    if status == 404 and "error" in reply:
        # The server gives both 404s as text only: an instance with no start, else a workflow outside its `run_safe`.
        raise CliError("unavailable" if message.startswith("no adapter can start") else "not_found", message)
    raise CliError("unavailable", f"{base}: {message}")


def _frames(base: str) -> Iterator[tuple[str, Any]]:
    """Each named event the server's stream sends, keep-alive comments skipped; the stream's end is an error."""
    try:
        events = urllib.request.Request(f"{base}/api/events", headers=_auth(base))
        with urllib.request.urlopen(events, timeout=_STREAM_TIMEOUT_S) as resp:
            name = ""
            for raw in resp:
                line = raw.decode().rstrip("\r\n")
                if line.startswith("event: "):
                    name = line.removeprefix("event: ")
                elif line.startswith("data: "):
                    yield name, json.loads(line.removeprefix("data: "))
    except urllib.error.HTTPError as exc:  # before OSError, which it subclasses
        raise CliError("unavailable", f"{base} answered {exc.code} for /api/events: is it a StarPulse server?") from exc
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot read StarPulse's events at {base}: {exc}") from exc
    raise CliError("unavailable", f"{base} closed the event stream")


def _delta(event: str, data: dict[str, Any], machine: str | None, task: str | None) -> dict[str, Any] | None:
    """The delta as `--machine` and `--task` leave it, None when they drop it.

    A `task` or `claim` delta is the Board's, a `move` delta its machine's, and `pulls` are the Board's tasks' with
    `--task` keeping only that task's. Workflow runs (`dags`) belong to neither, so any filter drops them.
    """
    if not (machine or task):
        return data
    if event == "pulls":
        pulls = {id_: found for id_, found in data["pulls"].items() if task in (None, id_)}
        return {"pulls": pulls} if pulls and machine in (None, "board") else None
    about = {
        "task": lambda d: ("board", d["id"]),
        "move": lambda d: (d["flow"], d["id"]),
        "claim": lambda d: ("board", d["task"]),
    }.get(event)
    if about is None:
        return None
    flow, id_ = about(data)
    return data if machine in (None, flow) and task in (None, id_) else None


def _watch(args: argparse.Namespace, environ: Mapping[str, str]) -> Iterator[dict[str, Any]]:
    """One line per change the server announces after the connect snapshot, the snapshot itself never."""
    base = server_url(args.server, environ)
    frames = _frames(base)
    name, snapshot = next(frames)
    if name != "snapshot" or not isinstance(snapshot, dict) or "flows" not in snapshot:
        raise CliError("unavailable", f"{base} opened its event stream with no snapshot: is it a StarPulse server?")
    flows = [flow["name"] for flow in snapshot["flows"]]
    if args.machine and args.machine not in flows:
        raise CliError("not_found", f"{args.machine} is not a machine; the server draws {', '.join(flows)}")
    for name, data in frames:
        if (delta := _delta(name, data, args.machine, args.task)) is not None:
            yield {"event": name, "data": delta}


def _health(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The Board's flow health as `/api/analytics/health` answers it; a window the server refuses is `refused`."""
    base = server_url(args.server, environ)
    asked = {"hours": args.hours, "stuck_hours": args.stuck_hours}
    query = urllib.parse.urlencode({key: value for key, value in asked.items() if value is not None})
    path = f"/api/analytics/health?{query}"
    status, document = _get(base, path)
    if status in {400, 501} and isinstance(document, dict) and "error" in document:
        raise CliError("refused" if status == 400 else "unavailable", document["error"])
    if status != 200 or not isinstance(document, dict) or not document.keys() >= set(_HEALTH_KEYS):
        raise CliError("unavailable", f"{base} answered {status} for {path}: is it a StarPulse server?")
    return {key: document[key] for key in _HEALTH_KEYS}


def _level_read(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    route: str,
    keys: Sequence[str],
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`keys` of what the level route `route` answers over `--hours`, with `params` added to the query.

    A window the server refuses, including one longer than its history, is `refused`; a server with no level is
    `unavailable`.
    """
    base = server_url(args.server, environ)
    query = urllib.parse.urlencode({**({} if args.hours is None else {"hours": args.hours}), **(params or {})})
    path = f"{route}?{query}"
    status, document = _get(base, path)
    if status in {400, 404, 501} and isinstance(document, dict) and "error" in document:
        raise CliError("refused" if status == 400 else "unavailable", document["error"])
    if status != 200 or not isinstance(document, dict) or not document.keys() >= set(keys):
        raise CliError("unavailable", f"{base} answered {status} for {path}: is it a StarPulse server?")
    return {key: document[key] for key in keys}


def _level(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The level's flow numbers and orbit shares as `/api/level` answers them."""
    return _level_read(args, environ, "/api/level", _LEVEL_KEYS)


def _trajectories(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The level's variants, norm, outliers, absorbing chain, betweenness and rework loops as
    `/api/level/trajectories` answers; each run keeps its path and loop counts, its gates being `gates`'."""
    document = _level_read(args, environ, "/api/level/trajectories", _TRAJECTORY_KEYS)
    document["runs"] = [
        {key: run[key] for key in ("source", "task", "path", "back_edges", "sccs", "loops")} for run in document["runs"]
    ]
    return document


def _gates(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Each gate's bypassability and witness for the level, and each run's own dominators and post-dominators.

    `--task` keeps one run's trajectory; the level's summary stays the level's. A task with no run that ended in the
    window is `not_found`.
    """
    document = _level_read(args, environ, "/api/level/trajectories", _GATE_KEYS)
    if args.task:
        runs = [run for run in document["runs"] if run["task"] == args.task]
        if not runs:
            raise CliError("not_found", f"{args.task} has no run that ended inside the window")
        document["runs"] = runs
    return document


def _forecast(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Each run still going with its chance of each terminal and its expected days, and the forecast's calibration.

    `--task` keeps one task's forecast; a task with no run still going is `not_found`.
    """
    document = _level_read(args, environ, "/api/level/trajectories", _FORECAST_KEYS)
    if args.task:
        forecast = [run for run in document["forecast"] if run["task"] == args.task]
        if not forecast:
            raise CliError("not_found", f"{args.task} has no run still going")
        document["forecast"] = forecast
    return document


def _steps(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """One row per model request over `--hours`, as `/api/analytics/steps` answers: the skill in force, the activities
    and keys of the calls it made, and its tokens. A window longer than the telemetry history is `refused`; a server
    that receives no telemetry is `unavailable`."""
    return _level_read(args, environ, "/api/analytics/steps", _STEP_KEYS)


def _transitions(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The cost of each skill in force within each kind and size over `--hours`, as `/api/analytics/transitions`
    answers. A window longer than the telemetry history is `refused`; a server that receives no telemetry is
    `unavailable`."""
    return _level_read(args, environ, "/api/analytics/transitions", _TRANSITION_KEYS)


def _cells(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The median steps per clean completion of each kind and size over `--hours`, as `/api/analytics/cells`
    answers; refusals as `analytics transitions`."""
    return _level_read(args, environ, "/api/analytics/cells", _CELL_KEYS)


def _graph(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The branching directly-follows graph of each skill's transition within each kind and size over `--hours`, as
    `/api/analytics/graph` answers; refusals as `analytics transitions`."""
    return _level_read(args, environ, "/api/analytics/graph", _GRAPH_KEYS)


def _stages(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The sub-stages mined from the stretches no skill governs over `--hours` against the `--hours` before, as
    `/api/analytics/stages` answers; refusals as `analytics transitions`."""
    return _level_read(args, environ, "/api/analytics/stages", _STAGE_KEYS)


def _diff(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Each transition's reference run against its slowest clean run over `--hours`, as `/api/analytics/diff`
    answers; refusals as `analytics transitions`."""
    return _level_read(args, environ, "/api/analytics/diff", _DIFF_KEYS)


def _what_if(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The change in the chance of the goal and the expected days when one transition has probability `--p`."""
    params = {"from": args.origin, "to": args.to, "p": args.p}
    return _level_read(args, environ, "/api/level/what-if", _WHAT_IF_KEYS, params)


def _doctor(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Every install check of `starpulse._internal.cli.doctor`; `ok` is false, and the exit code 1, when any fails."""
    base = server_url(args.server, environ)
    path = args.config or (Path("starpulse.toml") if Path("starpulse.toml").is_file() else None)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        config = f"{path}: {exc}"
    try:
        snapshot: dict[str, Any] | str = _get_snapshot(base)
    except CliError as exc:
        snapshot = str(exc)
    return doctor.run_checks(snapshot, config, doctor.LIVE, base)


def _skills_root(args: argparse.Namespace, environ: Mapping[str, str]) -> tuple[str, Path]:
    """Where a `skills` verb works: the project in the working directory, or with `--user` the home directory."""
    return ("user", Path(environ.get("HOME") or Path.home())) if args.user else ("project", Path.cwd())


def _skills_list(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    scope, root = _skills_root(args, environ)
    return {
        "scope": scope,
        "skills": [
            {
                "name": name,
                "description": skill_install.description(name),
                **{harness: skill_install.status(root, harness, name) for harness in skill_install.HARNESS_DIRS},
            }
            for name in skill_install.names()
        ],
    }


def _skills_install(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    harnesses = [harness for harness in skill_install.HARNESS_DIRS if getattr(args, harness)]
    if not harnesses:
        raise CliError("usage", "choose the harness to install for: --claude, --codex or both")
    scope, root = _skills_root(args, environ)
    try:
        return {"scope": scope, "installed": skill_install.install(root, harnesses, args.force)}
    except ValueError as exc:
        raise CliError("refused", str(exc)) from exc


def _checked(path: Path) -> dict[str, Any]:
    """One machine file's verdict: compiling it is what refuses a schema or a compile error."""
    from starpulse._internal.machines.machine_definition import MachineDefinitionError, Registry, load_machine  # noqa: PLC0415 - import cost, paid on first use

    try:
        load_machine(path, Registry(guards=_AnyName(), actions=_AnyName()))
    except MachineDefinitionError as error:
        errors = [{"file": str(error.file or path), "line": error.line, "message": str(error)}]
    else:
        errors = []
    return {"path": str(path), "ok": not errors, "errors": errors}


def _validate(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Every machine file checked; `ok` is false, and the exit code 1, when any is refused."""
    machines = [_checked(path) for path in args.paths]
    return {"ok": all(machine["ok"] for machine in machines), "machines": machines}


def _import_mermaid(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    from starpulse._internal.machines import mermaid_import  # noqa: PLC0415 - import cost, paid on first use
    from starpulse._internal.machines.machine_definition import MachineDefinitionError  # noqa: PLC0415 - import cost, paid on first use

    if not args.source.is_file():
        raise CliError("not_found", f"{args.source} is not a file")
    try:
        return {"written": str(mermaid_import.import_file(args.source, args.out))}
    except (MachineDefinitionError, OSError) as exc:
        raise CliError("refused", f"{args.source}: {exc}") from exc


def _plain(value: object) -> Any:
    """What JSON cannot hold, as text: a set as its sorted members, a regular expression as its pattern."""
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, re.Pattern):
        return value.pattern
    return str(value)


def _config_check(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The config as it would run, every default filled in; `ok` is false, and the exit code 1, when it would not."""
    path = args.config or (Path("starpulse.toml") if Path("starpulse.toml").is_file() else None)
    checked: dict[str, Any] = {"file": str(path) if path else None, "unknown_keys": [], "errors": [], "config": None}
    try:
        config = load(path)
    except ConfigError as exc:
        return {**checked, "ok": False, "unknown_keys": list(exc.unknown_keys), "errors": [str(exc)]}
    except (OSError, ValueError) as exc:  # a file that is missing or not TOML
        return {**checked, "ok": False, "errors": [f"{path}: {exc}"]}
    effective = json.loads(json.dumps(dataclasses.asdict(config), default=_plain))
    return {**checked, "ok": True, "config": effective}


def _demo(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    try:
        return {"written": str(demo.build(args.out, server_url(args.server, environ), args.mockup))}
    except urllib.error.URLError as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {server_url(args.server, environ)}: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise CliError("refused", str(exc)) from exc


def _help(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return _manifest(_parser())


def _leaves(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
) -> Iterator[tuple[str, argparse.ArgumentParser]]:
    """Each verb the parser dispatches to, as its words (`task show`) and its own parser."""
    for action in parser._actions:  # argparse offers no public way to list a parser's subcommands
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _leaves(sub, (*path, name))
            return
    yield " ".join(path), parser


def _manifest(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Every verb with its arguments, output keys and exit codes, read off the parser."""
    return {
        "exit_codes": {str(code): meaning for code, meaning in EXIT_CODES.items()},
        "verbs": [
            {
                "verb": verb,
                "summary": leaf.description,
                "arguments": [
                    {"name": a.dest, "flags": a.option_strings, "required": a.required, "help": a.help}
                    for a in leaf._actions
                    if a.dest != "help"
                ],
                "outputs": leaf.get_default("outputs"),
                "exit_codes": leaf.get_default("exit_codes"),
            }
            for verb, leaf in _leaves(parser)
            if leaf.get_default(
                "run"
            )  # `serve`, `emit`, `forward`, `connect`, `worker`, `import-history`, `conform` and `reload` are listed for `--help` but read no running server
        ],
    }


@functools.cache
def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="starpulse",
        description="StarPulse: workflows and tasks. These verbs read a running server as JSON.",
        epilog="`starpulse serve` runs the server, `starpulse emit` pushes a workflow run and `starpulse forward` sets the hub opt-in, `starpulse connect` sets up a tracker, `starpulse worker pulls` runs the pull request delivery loops alone, `starpulse worker autopilot` runs the autopilot alone `starpulse import-history` adds earlier lane changes to the store, `starpulse conform` replays the recorded history against the machines the project declares and `starpulse reload` replaces the serve children whose code changed; each has its own --help.",
    )
    verbs = parser.add_subparsers(dest="command", required=True, metavar="command")
    # Listed so `--help` shows how to start the server; `__main__` hands these words to their own parsers before this one.
    verbs.add_parser("serve", help="run StarPulse's server", add_help=False)
    verbs.add_parser("emit", help="push a workflow run onto the runs stream", add_help=False)
    verbs.add_parser("forward", help="let a person's name leave this instance for the hub, or stop it", add_help=False)
    verbs.add_parser("connect", help="set up a native, Backlog.md or Jira board in starpulse.toml", add_help=False)
    verbs.add_parser(
        "worker",
        help="run one context of the server as its own process (`worker pulls`, `worker autopilot`)",
        add_help=False,
    )
    verbs.add_parser(
        "import-history", help="add a board's earlier lane changes to the store, once each", add_help=False
    )
    verbs.add_parser(
        "conform", help="replay the recorded history against the machines the project declares", add_help=False
    )
    verbs.add_parser(
        "reload",
        help="replace the serve children whose code changed, reload those whose config changed",
        add_help=False,
    )

    def leaf(
        group: argparse._SubParsersAction,
        name: str,
        summary: str,
        run: Verb,
        outputs: Sequence[str],
        exit_codes: Sequence[int],
        *,
        reads_server: bool = True,
    ) -> argparse.ArgumentParser:
        sub = group.add_parser(name, description=summary, help=summary, allow_abbrev=False)
        sub.set_defaults(run=run, outputs=list(outputs), exit_codes=list(exit_codes))
        if reads_server:
            sub.add_argument("--server", help=f"the server's address, else $STARPULSE_URL, else {DEFAULT_SERVER}")
        return sub

    leaf(
        verbs,
        "snapshot",
        "the server's whole snapshot: every machine with its tasks, workflows and pull requests",
        _snapshot,
        _SNAPSHOT_KEYS,
        (0, 2, 3),
    )
    board = leaf(
        verbs,
        "board",
        "the Board's tasks per column, each with its dependencies, pull requests and legal moves",
        _board,
        ("columns",),
        (0, 2, 3),
    )
    board.add_argument("--state", help="only this column, by its state id (`in_progress`)")
    board.add_argument("--milestone", help="only tasks in this milestone")
    board.add_argument("--type", help="only tasks of this type (`spike`)")
    board.add_argument("--label", help="only tasks with this label")
    board.add_argument("--assignee", help="only tasks held by this assignee (`@agent-standard-high`)")
    board.add_argument("--holder", help="only tasks this session last claimed, as its harness names it")
    search = leaf(
        verbs,
        "search",
        "the tasks whose title, description, acceptance criteria or notes hold every word, best match first",
        _search,
        ("query", "hits"),
        (0, 1, 2, 3),
    )
    search.add_argument("query", nargs="+", help="the words to find (`signing keys`)")
    search.add_argument("--limit", type=int, help="at most this many hits, from 1 to 100 (default 10)")
    search.add_argument("--label", action="append", help="only tasks carrying this label; repeat for each (`disk`)")
    search.add_argument(
        "--finished-within-days",
        type=int,
        help="drop a task that finished (settled or entered Done) longer ago than this many days; open tasks stay",
    )
    task = verbs.add_parser("task", description="one task of the Board", help="one task of the Board")
    task_verbs = task.add_subparsers(dest="verb", required=True, metavar="verb")
    show = leaf(
        task_verbs,
        "show",
        "one task: its lane, dependencies and what it still waits on, pull requests and legal moves",
        _show,
        _TASK_KEYS,
        (0, 2, 3, 4),
    )
    show.add_argument("task", help="the task's key (`PROJ-45`)")
    moves = leaf(
        task_verbs,
        "moves",
        "every column a task may move to, each allowed or refused to the agent with its reason and skill",
        _moves,
        ("task", "lane", "moves"),
        (0, 2, 3, 4),
    )
    moves.add_argument("task", help="the task's key (`PROJ-45`)")
    move = leaf(
        task_verbs,
        "move",
        "move a task to a column as the agent; a refusal is the guard's verdict with its reason and skill",
        _move,
        _MOVE_KEYS,
        (0, 1, 2, 3, 4),
    )
    move.add_argument("task", help="the task's key (`PROJ-45`)")
    move.add_argument("to", help="the column's state id (`review`), as `task moves` lists")
    _writer_flags(move)
    claim = leaf(
        task_verbs,
        "claim",
        "claim a task for a session: it moves to In Progress holding that session; refused when another session holds it or this one holds another",
        _task_claim,
        _CLAIM_KEYS,
        (0, 1, 2, 3, 4),
    )
    claim.add_argument("task", help="the task's key (`PROJ-45`)")
    _writer_flags(claim)
    park = leaf(
        task_verbs,
        "park",
        "pause a task on one typed reason that picks the lane: --until-task or --until waits, --operator needs attention",
        _task_park,
        _LIFECYCLE_KEYS,
        (0, 1, 2, 3, 4),
    )
    park.add_argument("task", help="the task's key (`PROJ-45`)")
    park.add_argument("--until-task", action="append", default=[], help="a task that must reach Done first (repeatable)")
    park.add_argument("--until", action="append", default=[], help="a condition a check can observe, as YAML or JSON (repeatable)")
    park.add_argument("--operator", help="what only the operator can do or decide")
    park.add_argument("--comment", help="what is outstanding, recorded with the move")
    _writer_flags(park)
    review = leaf(
        task_verbs,
        "review",
        "move a task to Review with its evidence; the configured rules judge the record, a refusal names the rule and its skill",
        _task_review,
        _LIFECYCLE_KEYS,
        (0, 1, 2, 3, 4),
    )
    review.add_argument("task", help="the task's key (`PROJ-45`)")
    review.add_argument("--ref", action="append", default=[], help="evidence to add to the task's references, such as a pull request URL (repeatable)")
    review.add_argument("--summary", help="the task's final summary")
    review.add_argument("--comment", help="a comment recorded with the move")
    _writer_flags(review)
    trace = leaf(
        task_verbs,
        "trace",
        "a task's path: its Board lane changes, or with --flow its events on that machine, oldest first; a run id traces on --flow",
        _trace,
        ("task", "flow", "path", "steps"),
        (0, 2, 3, 4),
    )
    trace.add_argument("task", help="the task's key (`PROJ-45`), or with --flow a run id")
    trace.add_argument("--flow", help="the machine to trace the task on (`in-progress`), else the Board's lanes")
    create = leaf(
        task_verbs,
        "create",
        "open a task, whole, in one write, in the board's first lane or the one --status names, and return its new id",
        _task_create,
        ("task",),
        (0, 1, 2, 3),
    )
    _writer_flags(create)
    create.add_argument("title", help="the task's title")
    _create_flags(create)
    edit = leaf(
        task_verbs,
        "edit",
        "replace the fields given on a task in one write and return those that changed; refused whole when a field's value has changed since it was read",
        _task_edit,
        ("task", "changed"),
        (0, 1, 2, 3, 4),
    )
    _writer_flags(edit)
    edit.add_argument("task", help="the task's key (`PROJ-45`)")
    edit.add_argument("--title", help="the new title; blank is refused")
    edit.add_argument("--type", help="the task's type; blank removes it")
    edit.add_argument("--priority", help="`high`, `medium` or `low`; blank removes it")
    edit.add_argument("--milestone", help="the milestone's id; blank removes it")
    edit.add_argument("--label", action="append", help="a label; given at all, replaces the whole list (blank clears)")
    edit.add_argument("--dependency", action="append", help="a task it depends on; replaces the whole list")
    edit.add_argument("--reference", action="append", help="a reference; replaces the whole list")
    edit.add_argument("--documentation", action="append", help="a documentation link; replaces the whole list")
    edit.add_argument(
        "--modified-file", action="append", dest="modified_file", help="a modified file; replaces the whole list"
    )
    edit.add_argument("--description", help="the Description section")
    edit.add_argument("--plan", help="the Implementation Plan section")
    edit.add_argument("--notes", help="the Implementation Notes section")
    edit.add_argument("--final-summary", dest="final_summary", help="the Final Summary section")
    edit.add_argument(
        "--append-notes",
        action="append",
        dest="append_notes",
        help="a line to add to the end of the Implementation Notes, leaving what is there as written; repeat for several",
    )
    for key, item in (("ac", "Acceptance Criterion"), ("dod", "Definition of Done item")):
        article = "an" if item[0] in "AEIOU" else "a"
        edit.add_argument(
            f"--{key}", action="append", help=f"{article} {item} to add, unchecked; repeat for several, in order"
        )
        edit.add_argument(
            f"--reword-{key}",
            action="append",
            metavar="N:TEXT",
            help=f"the new wording of {item} #N, as `2:The new wording`; repeat for several",
        )
        for verb, does in (("remove", "removes"), ("check", "checks"), ("uncheck", "unchecks")):
            edit.add_argument(
                f"--{verb}-{key}",
                action="append",
                type=int,
                metavar="N",
                help=f"the number of the {item} it {does}{', renumbering the rest from 1' if verb == 'remove' else ''}; "
                "repeat for several",
            )
    edit.add_argument("--comment", default="", help="a comment to append to the task with the edit")
    edit.add_argument(
        "--base",
        help='a JSON object of the values the fields were read as (`{"priority": "high"}`); the edit is refused whole when '
        "any field it changes is no longer that value, else the task is read now",
    )
    assign = leaf(
        task_verbs,
        "assign",
        "set the task's assignee, refused when the board's writer refuses it",
        _task_assign,
        ("task", "assignee", "changed"),
        (0, 1, 2, 3, 4),
    )
    _writer_flags(assign)
    assign.add_argument("task", help="the task's key (`PROJ-45`)")
    assign.add_argument("assignee", help="who or which agent profile holds it (`@agent-standard-high`); blank clears")
    archive = leaf(
        task_verbs,
        "archive",
        "move a task from any lane to the board's archive, recording the reason when given",
        _task_archive,
        ("task",),
        (0, 1, 2, 3, 4),
    )
    _writer_flags(archive)
    archive.add_argument("task", help="the task's key (`PROJ-45`)")
    archive.add_argument("--reason", default="", help="why it is archived, recorded as a comment on the task")
    verdict = leaf(
        task_verbs,
        "verdict",
        "record a post-merge check's verdict as a comment on its task; a verdict is final",
        _task_verdict,
        ("task", "check", "verdict"),
        (0, 1, 2, 3, 4),
    )
    _writer_flags(verdict)
    verdict.add_argument("task", help="the task whose `## Post-merge Checks` block declares the check")
    verdict.add_argument("check", help="the check's id")
    verdict.add_argument("verdict", choices=("pass", "miss"), help="`pass`, or `miss` with --fix")
    verdict.add_argument("--evidence", default="", help="what the criterion showed, recorded with the verdict")
    verdict.add_argument("--fix", help="the task already filed to fix a miss (`PROJ-46`); required for `miss`")
    miss = leaf(
        task_verbs,
        "miss",
        "file the fix task for a missed post-merge check and record the MISS verdict naming it, both or neither",
        _task_miss,
        ("task", "check", "verdict", "fix"),
        (0, 1, 2, 3, 4),
    )
    _writer_flags(miss)
    miss.add_argument("task", help="the task whose `## Post-merge Checks` block declares the check")
    miss.add_argument("check", help="the check's id")
    miss.add_argument("--evidence", default="", help="what the criterion showed, recorded with the verdict")
    miss.add_argument("--title", required=True, help="the fix task's title")
    _create_flags(miss)
    restore = leaf(
        task_verbs,
        "restore",
        "return an archived task to the board's tasks, unchanged; refused when its number is open or its file name is taken",
        _task_restore,
        ("task",),
        (0, 1, 2, 3),
    )
    restore.add_argument("task", help="the archived or retired task's key (`PROJ-45`)")
    retire = leaf(
        task_verbs,
        "retire",
        "take a finished task off the board into the history store, kept byte-for-byte; refused when it is open",
        _task_retire,
        ("task",),
        (0, 1, 2, 3),
    )
    retire.add_argument("task", help="the Done, completed or archived task's key (`PROJ-45`)")
    retired = leaf(
        task_verbs,
        "retired",
        "the retired tasks the history store keeps, or the one named, each with its file name and text",
        _task_retired,
        ("tasks",),
        (0, 2, 3),
    )
    retired.add_argument("task", nargs="?", default="", help="one retired task's key (`PROJ-45`); default: every one")
    import_retired = leaf(
        task_verbs,
        "import-retired",
        "keep retired task files a client held in the history store; the same file again is accepted",
        _task_import_retired,
        ("tasks",),
        (0, 1, 2, 3),
    )
    import_retired.add_argument("files", nargs="+", help="each retired task's file (`retired/PROJ-3 - Old.md`)")
    complete = leaf(
        task_verbs,
        "complete",
        "move a Done task to the board's completed tasks; refused when it is not Done",
        _task_complete,
        ("task",),
        (0, 1, 2, 3, 4),
    )
    complete.add_argument("task", help="the task's key (`PROJ-45`)")
    checkpoint = leaf(
        task_verbs,
        "checkpoint-ac",
        "check one Acceptance Criterion and record its evidence in one write; refused when the task lacks it",
        _task_checkpoint_ac,
        ("task", "criterion", "changed"),
        (0, 1, 2, 3, 4),
    )
    _writer_flags(checkpoint)
    checkpoint.add_argument("task", help="the task's key (`PROJ-45`)")
    checkpoint.add_argument("criterion", type=int, help="the criterion's number (`2` for `#2`)")
    checkpoint.add_argument("evidence", help="what shows it holds, recorded as `Verified AC #N: <evidence>`")
    machine = verbs.add_parser(
        "machine",
        description="the machines the server draws and the machine files",
        help="the machines and their files",
    )
    machine_verbs = machine.add_subparsers(dest="verb", required=True, metavar="verb")
    leaf(
        machine_verbs,
        "list",
        "every machine the server draws, with its state ids and how many tasks are on it",
        _machines,
        ("machines",),
        (0, 2, 3),
    )
    show_machine = leaf(
        machine_verbs,
        "show",
        "one machine: its states with the live task count and tasks in each, its transitions, and the subflows, launches and writers it declares; `--format dot` adds a static Graphviz diagram",
        _machine,
        ("name", "states", "transitions"),
        (0, 2, 3, 4),
    )
    show_machine.add_argument("name", help="the machine's name (`board`, `in-progress`)")
    show_machine.add_argument(
        "--format",
        choices=("json", "dot"),
        default="json",
        help="`dot` adds the machine as Graphviz DOT source in `diagram`",
    )
    validate = leaf(
        machine_verbs,
        "validate",
        "check machine files against the schema and compile them, each error with its file and line",
        _validate,
        ("ok", "machines"),
        (0, 1, 2),
        reads_server=False,
    )
    validate.add_argument("paths", nargs="+", type=Path, help="the machine YAML files")
    importer = machine_verbs.add_parser("import", description="draft a machine file", help="draft a machine file")
    import_verbs = importer.add_subparsers(dest="source_kind", required=True, metavar="format")
    mermaid = leaf(
        import_verbs,
        "mermaid",
        "draft a machine file from a Mermaid stateDiagram-v2 file; guards and actions are left to write, and an existing file is never overwritten",
        _import_mermaid,
        ("written",),
        (0, 1, 2, 4),
        reads_server=False,
    )
    mermaid.add_argument("source", type=Path, help="the stateDiagram-v2 .mmd file")
    mermaid.add_argument("--out", type=Path, help="default: .starpulse/machines/<source name>.yaml")
    milestone = verbs.add_parser("milestone", description="the Board's milestones", help="the Board's milestones")
    milestone_verbs = milestone.add_subparsers(dest="verb", required=True, metavar="verb")
    milestone_list = leaf(
        milestone_verbs,
        "list",
        "every open milestone with its title, outcome, specs and ADRs",
        _milestone_list,
        ("milestones",),
        (0, 2, 3),
    )
    milestone_list.add_argument("--json", action="store_true", help="accepted for clarity: every verb prints JSON")
    milestone_show = leaf(
        milestone_verbs,
        "show",
        "one open milestone: its title, outcome, specs, ADRs, retro and whole description",
        _milestone_show,
        _MILESTONE_KEYS,
        (0, 2, 3, 4),
    )
    milestone_show.add_argument("milestone", help="the milestone's id (`m-106`), as `milestone list` shows it")
    milestone_add = leaf(
        milestone_verbs,
        "add",
        "open a milestone and return its new id",
        _milestone_add,
        ("milestone",),
        (0, 1, 2, 3),
    )
    milestone_add.add_argument("title", help="the milestone's title")
    milestone_edit = leaf(
        milestone_verbs,
        "edit",
        "replace the fields given on an open milestone and return those that changed",
        _milestone_edit,
        ("milestone", "changed"),
        (0, 1, 2, 3, 4),
    )
    milestone_edit.add_argument("milestone", help="the milestone's id (`m-106`)")
    milestone_edit.add_argument("--title", help="the new title; the file is renamed to match")
    for command in (milestone_add, milestone_edit):
        command.add_argument("--outcome", help="the milestone's Outcome section")
        command.add_argument(
            "--spec", action="append", help="a Spec bullet; repeat for more (replaces the list on edit)"
        )
        command.add_argument(
            "--adr", action="append", help="an ADRs bullet; repeat for more (replaces the list on edit)"
        )
        command.add_argument("--retro", help="the milestone's Retro section")
    milestone_archive = leaf(
        milestone_verbs,
        "archive",
        "move an open milestone to the board's archive",
        _milestone_archive,
        ("milestone",),
        (0, 1, 2, 3, 4),
    )
    milestone_archive.add_argument("milestone", help="the milestone's id (`m-106`)")
    doc = verbs.add_parser("doc", description="the Board's docs", help="the Board's docs")
    doc_verbs = doc.add_subparsers(dest="verb", required=True, metavar="verb")
    doc_list = leaf(
        doc_verbs, "list", "every open doc with its title, type, dates and path", _doc_list, ("docs",), (0, 2, 3)
    )
    doc_list.add_argument("--json", action="store_true", help="accepted for clarity: every verb prints JSON")
    doc_show = leaf(
        doc_verbs,
        "show",
        "one open doc: its title, type, dates, path and whole body",
        _doc_show,
        _DOC_KEYS,
        (0, 2, 3, 4),
    )
    doc_show.add_argument("doc", help="the doc's id (`doc-116`), as `doc list` shows it")
    doc_show.add_argument("--json", action="store_true", help="accepted for clarity: every verb prints JSON")
    doc_create = leaf(doc_verbs, "create", "file a doc and return its new id", _doc_create, ("doc",), (0, 1, 2, 3))
    doc_create.add_argument("title", help="the doc's title")
    doc_create.add_argument("--folder", help="a folder under the board's docs (`specs`); default: docs itself")
    doc_update = leaf(
        doc_verbs,
        "update",
        "replace the fields given on an open doc and return those that changed",
        _doc_update,
        ("doc", "changed"),
        (0, 1, 2, 3, 4),
    )
    doc_update.add_argument("doc", help="the doc's id (`doc-116`)")
    doc_update.add_argument("--title", help="the new title; the file is renamed to match")
    for command in (doc_create, doc_update):
        command.add_argument("--type", help="specification, guide, readme or other (the default on create)")
        command.add_argument("--body", help="the doc's whole text after its front matter")
    doc_archive = leaf(
        doc_verbs,
        "archive",
        "move an open doc to the board's archive",
        _doc_archive,
        ("doc",),
        (0, 1, 2, 3, 4),
    )
    doc_archive.add_argument("doc", help="the doc's id (`doc-116`)")
    doc_restore = leaf(
        doc_verbs,
        "restore",
        "return an archived doc to the board's docs, unchanged; refused when it is open or its destination exists",
        _doc_restore,
        ("doc",),
        (0, 1, 2, 3),
    )
    doc_restore.add_argument("doc", help="the archived doc's id (`doc-116`)")
    doc_restore.add_argument(
        "--folder", default="", help="a folder under the board's docs (`specs`); default: docs itself"
    )
    runs = verbs.add_parser("runs", description="the workflows of the runs adapters", help="its workflows")
    runs_verbs = runs.add_subparsers(dest="verb", required=True, metavar="verb")
    leaf(
        runs_verbs,
        "list",
        "every workflow as <instance>/<workflow> with its latest run's status, id and times",
        _runs,
        ("runs", "error"),
        (0, 2, 3),
    )
    start = leaf(
        runs_verbs,
        "start",
        "start a run-safe workflow through the server's Run now path and return its run id",
        _run_start,
        ("workflow", "run_id"),
        (0, 1, 2, 3, 4),
    )
    start.add_argument("workflow", help="the workflow as `runs list` names it (`prod/nightly`)")
    watch = leaf(
        verbs,
        "watch",
        "hold the event stream open and write one JSON line per change to a task, machine or workflow run",
        _watch,
        ("event", "data"),
        (0, 2, 3, 4),
    )
    watch.add_argument("--machine", help="only changes on this machine (`board`, `in-progress`)")
    watch.add_argument("--task", help="only changes to this task (`PROJ-45`)")
    analytics = verbs.add_parser(
        "analytics", description="flow health and level aggregates", help="flow health and level aggregates"
    )
    analytics_verbs = analytics.add_subparsers(dest="verb", required=True, metavar="verb")
    health = leaf(
        analytics_verbs,
        "health",
        "the Board's dwell and WIP per state, throughput and stuck tasks over a window, with history gap warnings",
        _health,
        _HEALTH_KEYS,
        (0, 1, 2, 3),
    )
    health.add_argument("--hours", type=float, help="the window to count over, in hours (default: the server's, 168)")
    health.add_argument("--stuck-hours", type=float, help="how long in one state makes a task stuck (default 24)")
    level = leaf(
        analytics_verbs,
        "level",
        "the level's WIP, throughput, time in state and aging, with each source's terminal and working-state shares",
        _level,
        _LEVEL_KEYS,
        (0, 1, 2, 3),
    )
    level.add_argument(
        "--hours", type=float, help="the window to count over, in hours; past the history it is refused (default 168)"
    )
    trajectories = leaf(
        analytics_verbs,
        "trajectories",
        "the runs that ended in the window as paths: variants and the norm, ranked outliers, the absorbing chain's "
        "expected days and chance of the goal, betweenness, the path-time bottleneck, and the rework loops each run took "
        "with the days they cost",
        _trajectories,
        _TRAJECTORY_KEYS,
        (0, 1, 2, 3),
    )
    trajectories.add_argument(
        "--hours",
        type=float,
        help="the window the runs ended in, in hours; past the history it is refused (default 168)",
    )
    gates = leaf(
        analytics_verbs,
        "gates",
        "each configured gate's bypassable flag and bypass witness path, and each run's own dominators and "
        "post-dominators of it",
        _gates,
        _GATE_KEYS,
        (0, 1, 2, 3, 4),
    )
    gates.add_argument(
        "--hours",
        type=float,
        help="the window the runs ended in, in hours; past the history it is refused (default 168)",
    )
    gates.add_argument("--task", help="only this task's trajectory (`PROJ-45`); the level's gate summary is unchanged")
    forecast = leaf(
        analytics_verbs,
        "forecast",
        "each run still going with its chance of each terminal and its expected days to finish, from its state's row "
        "conditioned on its loops so far with that row's sample size, and the forecast's per-decile calibration",
        _forecast,
        _FORECAST_KEYS,
        (0, 1, 2, 3, 4),
    )
    forecast.add_argument(
        "--hours",
        type=float,
        help="the window of ended runs the chain is fitted on, in hours; past the history it is refused (default 168)",
    )
    forecast.add_argument("--task", help="only this task's forecast (`PROJ-45`); the calibration is unchanged")
    what_if = leaf(
        analytics_verbs,
        "what-if",
        "the change in the chance of the goal and the expected days from the usual first state when one transition of "
        "the chain has another probability, its state's other exits keeping their shares of the rest",
        _what_if,
        _WHAT_IF_KEYS,
        (0, 1, 2, 3),
    )
    what_if.add_argument("--from", dest="origin", required=True, help="the state the transition leaves (`review`)")
    what_if.add_argument("--to", required=True, help="the state the transition enters (`in_progress`)")
    what_if.add_argument("--p", type=float, required=True, help="the transition's new probability, from 0 to 1")
    what_if.add_argument(
        "--hours",
        type=float,
        help="the window of ended runs the chain is fitted on, in hours; past the history it is refused (default 168)",
    )
    steps = leaf(
        analytics_verbs,
        "steps",
        "one row per model request: harness, session, task, time, model, the skill in force (`none` before any load), "
        "the activities and keys of the tool calls it made, and its tokens",
        _steps,
        _STEP_KEYS,
        (0, 1, 2, 3),
    )
    steps.add_argument(
        "--hours",
        type=float,
        help="the window to read, in hours; past the telemetry history it is refused (default 168)",
    )
    for verb, summary, run, answer in (
        (
            "transitions",
            "the cost of each skill in force within each kind and size: steps (a subagent's counted to its task), "
            "wasted-step rate, agent seconds and peak context",
            _transitions,
            _TRANSITION_KEYS,
        ),
        (
            "cells",
            "the median steps per clean completion of each kind and size over the latest fifth of its clean "
            "completions, with n, clean rate, median human prompts mid-task and median steps before the first edit",
            _cells,
            _CELL_KEYS,
        ),
        (
            "graph",
            "the branching directly-follows graph of each skill's transition within each kind and size: each activity "
            "edge with its run count, the edges leaving a judgement cut marked",
            _graph,
            _GRAPH_KEYS,
        ),
        (
            "stages",
            "the sub-stages mined at the judgement cuts of the stretches no skill governs, with their runs and median "
            "length this window and the one before and how stable the stages are from one to the other",
            _stages,
            _STAGE_KEYS,
        ),
        (
            "diff",
            "each transition's reference run (the fewest-step clean completion that conforms to its machine, from at "
            "least 5) against its slowest clean run: the activities the slow run made that the reference did not",
            _diff,
            _DIFF_KEYS,
        ),
    ):
        leaf(analytics_verbs, verb, summary, run, answer, (0, 1, 2, 3)).add_argument(
            "--hours",
            type=float,
            help="the window to read, in hours; past the telemetry history it is refused (default 168)",
        )
    config = verbs.add_parser("config", description="the config file", help="the config file")
    config_verbs = config.add_subparsers(dest="verb", required=True, metavar="verb")
    config_check = leaf(
        config_verbs,
        "check",
        "load the config: unknown keys by name and the effective config with its defaults",
        _config_check,
        ("ok", "file", "unknown_keys", "errors", "config"),
        (0, 1, 2),
        reads_server=False,
    )
    config_check.add_argument("--config", type=Path, help="the TOML config file; default starpulse.toml when it exists")
    page = leaf(
        verbs,
        "demo",
        "build the self-contained demo page: the server's structure with every task replaced by a synthetic one",
        _demo,
        ("written",),
        (0, 1, 2, 3),
    )
    page.add_argument("--out", type=Path, required=True, help="the HTML file to write")
    page.add_argument("--mockup", type=Path, help="a design mockup directory to build instead of the server's page")
    check = leaf(
        verbs,
        "doctor",
        "check the install: config, the server, each adapter producing and gh, each pass or fail",
        _doctor,
        ("ok", "checks"),
        (0, 1, 2),
    )
    check.add_argument("--config", type=Path, help="the TOML config file; default starpulse.toml when it exists")
    skills = verbs.add_parser("skills", description="the skills StarPulse bundles", help="the skills StarPulse bundles")
    skill_verbs = skills.add_subparsers(dest="verb", required=True, metavar="verb")
    listing = leaf(
        skill_verbs,
        "list",
        "each bundled skill with whether each harness has it installed, outdated or modified, or not at all",
        _skills_list,
        ("scope", "skills"),
        (0, 2),
        reads_server=False,
    )
    install = leaf(
        skill_verbs,
        "install",
        "copy the bundled skills to each chosen harness's skills directory; refuses a copy modified since install",
        _skills_install,
        ("scope", "installed"),
        (0, 1, 2),
        reads_server=False,
    )
    for sub in (listing, install):
        sub.add_argument("--user", action="store_true", help="the home directory's skills, not this project's")
    install.add_argument("--claude", action="store_true", help="install for Claude Code, into .claude/skills")
    install.add_argument("--codex", action="store_true", help="install for Codex, into .agents/skills")
    install.add_argument("--force", action="store_true", help="replace a copy modified since install")
    manifest = leaf(
        verbs,
        "help",
        "the verb manifest: verbs, arguments, output keys and exit codes",
        _help,
        ("exit_codes", "verbs"),
        (0, 2),
        reads_server=False,
    )
    manifest.add_argument("--agent", action="store_true", required=True, help="print the manifest as JSON")
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] = os.environ) -> int:
    """Run one verb and print its JSON document; the exit code is the document's, as `EXIT_CODES` lists."""
    try:
        args = _parser().parse_args(argv)
        result = args.run(args, environ)
        if not isinstance(result, dict):  # a stream: each line is written as it arrives, until an error or an interrupt
            for line in result:
                print(json.dumps(line), flush=True)
            return 0
        document, status = result, 0 if result.get("ok", True) else 1  # only `doctor` reports `ok`
    except CliError as exc:
        document, status = {"error": str(exc), "code": exc.code}, _ERROR_EXIT[exc.code]
    except KeyboardInterrupt:  # the one way a `watch` ends well
        return 0
    print(json.dumps(document))
    return status
