"""The Codex adapter: Codex hook payloads and session rollouts become events on the harness machine.

A hook (`SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop`) is mapped through the machine's
`bindings`; a rollout (`$CODEX_HOME/sessions/Y/M/D/rollout-*.jsonl`) is replayed record by record,
so a session that ran without the hooks installed still draws. A tool call that reads a
`skills/<name>/SKILL.md` is a skill use, any other call a tool use. An event is keyed by the task
the session's git branch names under the adapter's `TaskKeys`, else by the session as a run.

The adapter depends on nothing of trantor's: not its hooks, its `AGENTS.md` or its branch names.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from starpulse._internal.harnesses.harness import HARNESS
from starpulse.contracts.adapters import TaskKeys

ACTOR = "codex"
_SKILL = re.compile(r"skills/[\w.-]+/SKILL\.md")
#: The rollout record payloads that are a tool call, as opposed to its output.
_CALLS = frozenset({"custom_tool_call", "function_call", "local_shell_call"})

_GIT: dict[str, Any] = {
    "capture_output": True,
    "text": True,
    "check": False,
    "timeout": 5,
}  # pragma: no mutate: check=False is the default and the timeout only a bound


def git_branch(cwd: str) -> str | None:
    """The branch checked out in `cwd`, or None when it is not a git work tree, HEAD is detached or git cannot run."""
    try:
        done = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], **_GIT)
    except OSError, subprocess.TimeoutExpired:
        return None
    return done.stdout.strip() or None  # git prints a failure to stderr, so stdout is empty


@dataclass(frozen=True)
class CodexAdapter:
    """Maps Codex's records onto `MachineEvent` dicts for `keys`' task scheme."""

    keys: TaskKeys
    #: The branch a working directory has checked out; the task a branch names keys the session's events.
    branch_of: Callable[[str], str | None] = git_branch
    clock: Callable[[], float] = lambda: datetime.now().timestamp()

    def rollout(self, path: Path) -> list[dict]:
        """The events a rollout replays, in order: each turn starts the session and its stop ends it."""
        session, cwd, events = (
            "",
            "",
            [],
        )
        task_of = cache(self._task_of)  # one lookup per directory in this replay; a later call sees a new branch
        for record in _records(path):
            payload: dict[str, Any] = record["payload"] if isinstance(record.get("payload"), dict) else {}
            if record.get("type") == "session_meta":
                session, cwd = str(payload.get("id") or session), str(payload.get("cwd") or cwd)
                continue
            event = _rollout_event(record["type"], payload)
            if event is not None and session:
                events.append(self._event(event, session, task_of(cwd), _epoch(record["timestamp"])))
        return events

    def hook(self, payload: Mapping[str, Any]) -> dict | None:
        """The event a hook payload moves the machine by, or None for a hook the machine does not bind."""
        name, session = payload.get("hook_event_name"), payload.get("session_id")
        event = HARNESS.bindings.get(name) if isinstance(name, str) else None
        if event is None or not isinstance(session, str) or not session:
            return None
        if event == "TOOL_USED" and _SKILL.search(json.dumps(payload.get("tool_input"))):
            event = "SKILL_USED"
        return self._event(event, session, self._task_of(str(payload.get("cwd") or "")), self.clock())

    def _task_of(self, cwd: str) -> str | None:
        return self.keys.for_branch(self.branch_of(cwd)) if cwd else None

    def _event(self, event: str, session: str, task: str | None, time: float) -> dict:
        return {
            "machine": HARNESS.name,
            "event": event,
            "task": task,
            "run": None if task else session,
            "actor": ACTOR,
            "time": time,
        }


def _records(path: Path) -> list[dict]:
    """The JSON object each line of a rollout holds; a line being written when read is skipped."""
    records = []
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("type"), str) and _is_time(record.get("timestamp")):
            records.append(record)
    return records


def _rollout_event(kind: str, payload: Mapping[str, Any]) -> str | None:
    if kind == "event_msg":
        return {"task_started": "SESSION_STARTED", "task_complete": "SESSION_STOPPED"}.get(str(payload.get("type")))
    if kind == "response_item" and payload.get("type") in _CALLS:
        return "SKILL_USED" if _SKILL.search(json.dumps(payload)) else "TOOL_USED"
    return None


def _is_time(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        _epoch(value)
    except ValueError:
        return False
    return True


def _epoch(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp).timestamp()
