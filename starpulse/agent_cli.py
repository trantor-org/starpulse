"""`starpulse snapshot|board|task|machine|runs|watch|analytics|doctor|skills|help --agent`: the verbs an agent drives a running server with.

    starpulse board --milestone launch --label api
    starpulse task show PROJ-45
    starpulse task moves PROJ-45
    starpulse task move PROJ-45 review
    starpulse task trace PROJ-45 --flow in-progress
    starpulse machine show in-progress
    starpulse runs list
    starpulse runs start prod/nightly
    starpulse watch --machine in-progress --task PROJ-45
    starpulse analytics health --hours 72
    starpulse analytics level --hours 48
    starpulse doctor
    starpulse skills install --claude --codex
    starpulse help --agent

Every verb writes one JSON document to stdout, an error as `{"error": "...", "code": "..."}`, and nothing to stderr.
`task move` always moves as the actor `agent`, naming its session when `--session` or `STARPULSE_SESSION` gives one: a claim
(a move to `in_progress`) records that session as the task's holder, and the board writer may answer with `advice`. A move the board machine declares for the operator alone, or that the
board's guard refuses, is `{"ok": false, "reason": "...", "skill": "..."}`, the verdict, and exit 1.
The exit code is 0 for success (for `doctor`, every check passing), 1 for a refused or invalid request, a refused
move or a failed `doctor` check, 2 for a usage error, 3 when the server (or what the
verb needs of it) is unavailable and 4 for something not found. The server is `--server`, else `STARPULSE_URL`, else
`http://localhost:8766`; a verb reads it per call and keeps nothing. `starpulse help --agent` prints the manifest of
verbs, generated from the parser below, so a verb added here is listed with its arguments, output keys and exit codes.
`watch` is the one verb that writes more than one document: it holds the server's event stream open and writes one JSON
line, `{"event": "task|move|pulls|claim|dags", "data": {...}}`, per change that `--machine` and `--task` leave in, until
it is interrupted (exit 0) or the server ends the stream (an error line, exit 3). `runs start` calls the server's Run
now path, so its LAN and `run_safe` guards apply to the agent as they do to the page.
`skills` reads no server: it copies the bundled skills into the project or, with `--user`, the home directory.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

from starpulse import demo, doctor, mermaid_import, skill_install
from starpulse.config import ConfigError, load
from starpulse.contracts import Move
from starpulse.machine_definition import MachineDefinitionError, Registry, load_machine

#: serve's default `--port`, where a server runs unless the caller says otherwise.
DEFAULT_SERVER = "http://localhost:8766"
#: Who `task move` moves as: the machine YAML's writers say which moves an agent may make.
AGENT = "agent"
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
    "claims",
    "settled",
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
_HEALTH_KEYS = ("now", "window_s", "stuck_after_s", "states", "throughput", "stuck", "warnings")
_TASK_KEYS = (
    "id",
    "title",
    "lane",
    "assignee",
    "milestone",
    "labels",
    "dependencies",
    "waiting_on",
    "prs",
    "moves",
    "description",
)
_MOVE_KEYS = ("ok", "task", "to", "reason", "skill", "advice")
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


_ADAPTER_NAMES = Registry(guards=_AnyName(), actions=_AnyName())


class CliError(Exception):
    """A request a verb cannot answer: `code` is one of `_ERROR_EXIT`, the message says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _Parser(argparse.ArgumentParser):
    """A parser whose usage errors are `CliError`s, so they reach stdout as JSON instead of stderr as text."""

    def error(self, message: str) -> NoReturn:
        raise CliError("usage", message)


def server_url(flag: str | None, environ: Mapping[str, str]) -> str:
    """The server to read: the `--server` flag, else `STARPULSE_URL`, else the default, without a trailing slash."""
    return (flag or environ.get("STARPULSE_URL") or DEFAULT_SERVER).rstrip("/")


def _get(base: str, path: str) -> tuple[int, Any]:
    """The status and JSON body the server at `base` answers `path` with; None for a body that is no JSON."""
    try:
        with urllib.request.urlopen(
            f"{base}{path}",
            timeout=10.0,  # seconds the server may take to answer one read
        ) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, None
    except (OSError, ValueError) as exc:
        raise CliError("unavailable", f"cannot reach StarPulse at {base}: {exc}") from exc


def _get_snapshot(base: str) -> dict[str, Any]:
    """The snapshot the server at `base` answers; JSON without every snapshot key is no StarPulse server."""
    path = "/api/snapshot"
    status, document = _get(base, path)
    if status != 200:
        raise CliError("unavailable", f"{base} answered {status} for {path}: is it a StarPulse server?")
    if not isinstance(document, dict) or not document.keys() >= set(_SNAPSHOT_KEYS):
        raise CliError("unavailable", f"{base} answered {path} with no StarPulse snapshot: is it a StarPulse server?")
    return document


def _snapshot(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return _get_snapshot(server_url(args.server, environ))


def _board_flow(snapshot: dict[str, Any]) -> dict[str, Any]:
    return next(flow for flow in snapshot["flows"] if flow["name"] == "board")


def _agent_moves(agent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The verdict on each column as the agent meets it: a move the board machine leaves to others is refused."""
    return {
        column: Move.model_validate(raw).for_actor(AGENT).model_dump(include={"allowed", "reason", "skill"})
        for column, raw in agent["moves"].items()
    }


def _task(agent: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """A Board task as a verb reports it. It waits on each dependency that has not completed."""
    pulls = {pull["url"]: pull for pull in snapshot["pulls"].get(agent["id"], [])}
    return {
        "id": agent["id"],
        "title": agent["title"],
        "lane": agent["state"],
        "assignee": agent["model"],
        "milestone": agent["milestone"],
        "labels": agent["labels"],
        "dependencies": agent["dependencies"],
        "waiting_on": [d for d in agent["dependencies"] if (snapshot["settled"].get(d) or {}).get("state") != "completed"],
        "prs": [pulls.get(url, {"url": url}) for url in agent["prs"]],
        "moves": _agent_moves(agent),
    }


def _board(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = _snapshot(args, environ)
    board = _board_flow(snapshot)
    states = board["machine"]["states"]
    if args.state and args.state not in (ids := [s["id"] for s in states]):
        raise CliError("usage", f"unknown state {args.state}; the board has {', '.join(ids)}")

    def kept(agent: dict[str, Any]) -> bool:
        return (
            (not args.milestone or agent["milestone"] == args.milestone)
            and (not args.label or args.label in agent["labels"])
            and (not args.assignee or agent["model"] == args.assignee)
        )

    return {
        "columns": [
            {
                "state": state["id"],
                "name": state["name"],
                "tasks": [_task(a, snapshot) for a in board["agents"] if a["state"] == state["id"] and kept(a)],
            }
            for state in states
            if not args.state or state["id"] == args.state
        ]
    }


def _show(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    snapshot = _snapshot(args, environ)
    agents = {agent["id"]: agent for agent in _board_flow(snapshot)["agents"]}
    if (agent := agents.get(args.task)) is None:
        if (settled := snapshot["settled"].get(args.task)) is None:
            raise CliError("not_found", f"{args.task} is not on the board")
        # A settled task has left the lanes, and the snapshot keeps only where it settled.
        agent = {
            "id": args.task,
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
    return {**_task(agent, snapshot), "description": agent["description"]}


def _moves(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    shown = _show(args, environ)
    return {"task": shown["id"], "lane": shown["lane"], "moves": shown["moves"]}


def _move(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Move the task as the agent: the server's verdict, or an error when no board writer can answer."""
    base = server_url(args.server, environ)
    session = args.session or environ.get("STARPULSE_SESSION", "")
    body = {"task": args.task, "to": args.to, "actor": AGENT, **({"session": session} if session else {})}
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


def _post(base: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """The status and JSON object the server at `base` answers a POST of `body` to `path` with; {} for any other body."""
    request = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"
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
    return {
        "name": flow["name"],
        "states": [
            {**state, "count": len(tasks[state["id"]]), "tasks": tasks[state["id"]]} for state in machine["states"]
        ],
        "transitions": machine["transitions"],
    }


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
        with urllib.request.urlopen(f"{base}/api/events", timeout=_STREAM_TIMEOUT_S) as resp:
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


def _level(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """The level's flow numbers and orbit shares as `/api/level` answers them.

    A window the server refuses, including one longer than its history, is `refused`; a server with no level is
    `unavailable`.
    """
    base = server_url(args.server, environ)
    query = urllib.parse.urlencode({} if args.hours is None else {"hours": args.hours})
    path = f"/api/level?{query}"
    status, document = _get(base, path)
    if status in {400, 404, 501} and isinstance(document, dict) and "error" in document:
        raise CliError("refused" if status == 400 else "unavailable", document["error"])
    if status != 200 or not isinstance(document, dict) or not document.keys() >= set(_LEVEL_KEYS):
        raise CliError("unavailable", f"{base} answered {status} for {path}: is it a StarPulse server?")
    return {key: document[key] for key in _LEVEL_KEYS}


def _doctor(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    """Every install check of `starpulse.doctor`; `ok` is false, and the exit code 1, when any fails."""
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
    try:
        load_machine(path, _ADAPTER_NAMES)
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
    if not args.source.is_file():
        raise CliError("not_found", f"{args.source} is not a file")
    try:
        return {"written": str(mermaid_import.import_file(args.source, args.out))}
    except (MachineDefinitionError, OSError) as exc:
        raise CliError("refused", f"{args.source}: {exc}") from exc


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
    effective = json.loads(json.dumps(dataclasses.asdict(config), default=str))
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
            if leaf.get_default("run")  # `serve`, `emit` and `forward` are listed for `--help` but read no running server
        ],
    }


@functools.cache
def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="starpulse",
        description="StarPulse: the flow view of workflows and tasks. These verbs read a running server as JSON.",
        epilog="`starpulse serve` runs the server, `starpulse emit` pushes a workflow run and `starpulse forward` sets the hub opt-in; each has its own --help.",
    )
    verbs = parser.add_subparsers(dest="command", required=True, metavar="command")
    # Listed so `--help` shows how to start the server; `__main__` hands these words to their own parsers before this one.
    verbs.add_parser("serve", help="run the flow view's server", add_help=False)
    verbs.add_parser("emit", help="push a workflow run onto the runs stream", add_help=False)
    verbs.add_parser("forward", help="let a person's name leave this instance for the hub, or stop it", add_help=False)

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
    board.add_argument("--label", help="only tasks with this label")
    board.add_argument("--assignee", help="only tasks held by this assignee (`@agent-standard-high`)")
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
    move.add_argument(
        "--session",
        default="",
        help="the session making the move, recorded as the holder of a claimed task (else `STARPULSE_SESSION`)",
    )
    trace = leaf(
        task_verbs,
        "trace",
        "a task's path: its Board lane changes, or with --flow its events on that machine, oldest first",
        _trace,
        ("task", "flow", "path", "steps"),
        (0, 2, 3, 4),
    )
    trace.add_argument("task", help="the task's key (`PROJ-45`)")
    trace.add_argument("--flow", help="the machine to trace the task on (`in-progress`), else the Board's lanes")
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
        "one machine: its states with the live task count and tasks in each, and its transitions",
        _machine,
        ("name", "states", "transitions"),
        (0, 2, 3, 4),
    )
    show_machine.add_argument("name", help="the machine's name (`board`, `in-progress`)")
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
