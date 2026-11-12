"""The MCP server a session holding a task talks to: it lists only the exit tools of the lane the task is in.

A lane's `tools` scope the harness's own tools (`lane_scope`); its exit tools are served here, generated from the lane's
exits in the policy `/api/machines` serves. A call to any other tool is refused before anything runs, and an exit that
lands the task in a lane answers with that lane's bound skill.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

__all__ = ["LaneTools", "main", "serve", "task_of_branch"]

_BRANCH = re.compile(r"^claude/task-(\d+)-")
_TASK = re.compile(r"^TASK-\d+$")
_TASK_REF = re.compile(r"^TASK-\d+(#\d+)?$")
_SKILL = re.compile(r"^[A-Za-z0-9_-]+$")
_PROTOCOL = "2025-03-26"


class LaneTools:
    def __init__(
        self,
        task: str,
        lanes: Callable[[], dict[str, Any]],
        lane_of: Callable[[], str | None],
        run: Callable[[list[str]], dict[str, Any]],
        skill_text: Callable[[str], str],
        scoped: Callable[[list[str]], None] = lambda tools: None,
    ) -> None:
        self._task, self._lanes, self._lane_of, self._run, self._skill_text = task, lanes, lane_of, run, skill_text
        self._scoped = scoped

    def handle(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """The messages that answer one request (none for a notification)."""
        method, ident = message.get("method", ""), message.get("id")
        if ident is None:
            return []
        if method == "initialize":
            lane = self._lane_of()
            self._scope(lane)
            result: dict[str, Any] = {
                "protocolVersion": _PROTOCOL,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "starpulse-lane", "version": "1"},
                "instructions": self._entered(lane),
            }
        elif method == "tools/list":
            result = {"tools": [_listed(tool) for tool in self._exits()]}
        elif method == "tools/call":
            params = message.get("params")
            reply, entered = self._call(params if isinstance(params, dict) else {})
            return [
                {"jsonrpc": "2.0", "id": ident, "result": reply},
                *([{"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}] if entered else []),
            ]
        elif method == "ping":
            result = {}
        else:
            return [{"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"no method {method}"}}]
        return [{"jsonrpc": "2.0", "id": ident, "result": result}]

    def _scope(self, lane: str | None) -> None:
        """Scope the harness's tools to `lane`; a lane that cannot be read leaves the scope as it was."""
        if lane:
            self._scoped(self._lanes().get(lane, {}).get("tools", []))

    def _entered(self, lane: str | None) -> str:
        """What the session is told on holding `lane`: where its task is and the lane's bound skill."""
        if not lane:
            return f"{self._task}'s lane could not be read, so this server lists no exit tools and leaves the tools as they were."
        skill = self._lanes().get(lane, {}).get("skill")
        text = f"{self._task} is now in {lane}."
        if skill:
            text += f"\n\nThe skill bound to {lane}, {skill}:\n\n{self._skill_text(skill)}"
        return text

    def _exits(self) -> list[dict[str, Any]]:
        lane = self._lane_of()
        return self._lanes().get(lane, {}).get("exits", []) if lane else []

    def _call(self, params: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        name, arguments = params.get("name", ""), params.get("arguments", {})
        tool = next((tool for tool in self._exits() if tool["name"] == name), None)
        if tool is None:
            held = ", ".join(t["name"] for t in self._exits()) or "none"
            return _text(f"{name} is not a tool of the lane {self._task} holds; its exit tools: {held}", True), False
        refusal = _refused(tool["schema"], arguments)
        if refusal:
            return _text(f"{name}: {refusal}", True), False
        document = self._run(_argv(tool, self._task, arguments))
        if "error" in document or document.get("ok") is False:
            return _text(json.dumps(document), True), False
        lane = self._lane_of()
        self._scope(lane)
        return _text(self._entered(lane), False), True


def _listed(tool: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "description": f"Fire {tool['event']}: the task moves to {tool['to']}.",
        "inputSchema": tool["schema"],
    }


def _text(text: str, error: bool) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _refused(schema: Mapping[str, Any], arguments: object) -> str | None:
    error = best_match(Draft202012Validator(schema).iter_errors(arguments))
    if error is None:
        return None
    argument = ".".join(str(key) for key in error.path)
    match error.validator:
        case "pattern":
            return f"{argument} must not be blank"
        case "type":
            return f"{argument} must be text" if argument else "arguments must be an object"
        case _:
            return error.message


def _argv(tool: Mapping[str, Any], task: str, arguments: Mapping[str, Any]) -> list[str]:
    match tool["name"]:
        case "board_park":
            until = arguments.get("until", "")
            flag = "--until-task" if _TASK_REF.match(until) else "--until"
            return ["task", "park", task, f"--comment={arguments['reason']}", *([f"{flag}={until}"] if until else [])]
        case "board_defer":
            return ["task", "park", task, f"--operator={arguments['question']}"]
        case "board_finalize":
            return ["command", "run", "finalize", "--task", task]
        case _:
            return ["task", "move", task, tool["to"]]


def task_of_branch(branch: str) -> str | None:
    """The task a `claude/task-<n>-…` branch is for."""
    found = _BRANCH.match(branch)
    return f"TASK-{found.group(1)}" if found else None


def lane_of(task: str) -> str | None:
    """The lane `task show` reports for `task`, None when it reports none."""
    return _in_process(["task", "show", task]).get("lane")


def _in_process(argv: list[str]) -> dict[str, Any]:
    """One agent CLI verb run here, and the JSON document it printed."""
    from starpulse.cli import agent_cli  # noqa: PLC0415 - import cost, paid only by a call that reaches the server

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = agent_cli.main(argv)
    lines = out.getvalue().strip().splitlines()
    try:
        document = json.loads(lines[-1]) if lines else {}
    except ValueError:
        document = {}
    if not isinstance(document, dict):
        document = {}
    return document if status == 0 else {**document, "error": document.get("error", out.getvalue())}


def _skill_text(root: Path, name: str) -> str:
    """The body of the project's skill `name` (`plugin:skill` reads `skill`), else the instruction to invoke it."""
    leaf = name.rsplit(":", 1)[-1]
    for directory in (".claude/skills", ".agents/skills") if _SKILL.match(leaf) else ():
        path = root / directory / leaf / "SKILL.md"
        if path.is_file():
            return path.read_text()
    return f"Invoke the skill `{name}`."


def serve(tools: LaneTools, stdin: TextIO, stdout: TextIO) -> None:
    """Answer each JSON-RPC line of `stdin`; a line that is not a request, or a request that fails, gets an error reply."""
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("a request is a JSON object")
        except ValueError as exc:
            replies = [{"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}]
        else:
            try:
                replies = tools.handle(message)
            except (OSError, ValueError, KeyError) as exc:
                replies = [{"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32000, "message": str(exc)}}]
        for reply in replies:
            print(json.dumps(reply), file=stdout, flush=True)


def main(argv: list[str], stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    """Serve the lane tools of the task the current branch is for over stdio, one JSON-RPC message a line."""
    from starpulse.cli import agent_wire  # noqa: PLC0415 - import cost, paid only by a run that serves
    from starpulse.cli.lane_scope import scope  # noqa: PLC0415 - import cost, paid only by a run that serves

    root = Path.cwd()
    branch = subprocess.run(  # noqa: S603 - a fixed argv
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=root, check=False  # noqa: S607
    ).stdout.strip()
    task = os.environ.get("STARPULSE_TASK") or task_of_branch(branch)
    if task is None or not _TASK.match(task):
        print(f"starpulse mcp: {task or branch!r} names no task; set STARPULSE_TASK to TASK-<n>", file=sys.stderr)
        return 2
    base = agent_wire.server_url(None, os.environ)

    def lanes() -> dict[str, Any]:
        _, body = agent_wire.get(base, "/api/machines")
        return body.get("lanes", {})

    tools = LaneTools(
        task, lanes, lambda: lane_of(task), _in_process, lambda name: _skill_text(root, name), lambda allowed: scope(root, allowed)
    )
    serve(tools, stdin, stdout)
    return 0
