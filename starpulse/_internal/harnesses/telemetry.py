"""The signals session and slice health fold, read from Claude Code's and Codex's OTLP/HTTP log exports.

An export is `resourceLogs[].scopeLogs[].logRecords[]`, each record a bag of typed attributes. A record becomes one
`Signal`, keyed by the harness's own session id (`session.id` for Claude Code, `conversation.id` for Codex) and ordered
by its `event.timestamp`. Codex names its event in the `event.name` attribute, which wins over the log record's own
`eventName`, since the attribute is what the exporter sets.

What a signal keeps is a count, a duration, a model or effort name, a tool, skill or decision name and the branch;
the prompt, reply, tool output and account fields every such record also carries are never read, and a shell tool's
input is read only for the `git switch` or `git checkout` ref it names, which is kept as a `branch` signal.

| harness | records read |
|---|---|
| Claude Code | `user_prompt`, `api_request`, `tool_decision`, `tool_result`, `skill_activated`, `compaction` |
| Codex | `codex.conversation_starts`, `codex.user_prompt`, `codex.sse_event` (`response.completed`), `codex.tool_decision`, `codex.tool_result`, `codex.skill_invocation`, `codex.turn_cost` (an interrupted turn) |
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, fields
from typing import Any

from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.harnesses.activity import SHELLS, activities, elide_heredocs, paths
from starpulse._internal.harnesses.otlp import BRANCH, _attributes, _epoch, _records
from starpulse._internal.level.signals import CLAUDE_CODE, CODEX, Signal

__all__ = ["CLAUDE_CODE", "CODEX", "Signal", "TelemetryLog", "redactor", "signals"]

log = logging.getLogger(__name__)

#: Where Codex runs its main agent; a tool result from any other agent path is a subagent's.
_MAIN_AGENT = {"", "/root"}
#: `git switch` or `git checkout`, its flags, then the ref it names (never a `--` pathspec).
_SWITCH = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:switch|checkout)\s+((?:-[\w-]+\s+)*)([^\s;&|<>-][^\s;&|<>]*)")


def _number(value: Any) -> int:
    try:
        return max(int(float(str(value))), 0)
    except ValueError:
        return 0


def _seconds(value: Any) -> float:
    return _number(value) / 1000


def _flag(value: Any) -> bool:
    return str(value).lower() == "true"


def _cost(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _input(attributes: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """A tool call's input as the export gave it: Claude Code's `tool_input` or Codex's `arguments`, parsed when it is
    a JSON object, and its raw text."""
    for key in ("tool_input", "arguments"):
        if (raw := attributes.get(key)) is None:
            continue
        try:
            parsed = json.loads(str(raw))
        except ValueError:
            return {}, str(raw)
        return (parsed if isinstance(parsed, dict) else {}), str(raw)
    return {}, ""


def _command(tool_input: dict[str, Any]) -> str:
    """The shell command a tool call ran."""
    command = tool_input.get("command") or tool_input.get("cmd")
    return command if isinstance(command, str) else ""


def _call(attributes: dict[str, Any]) -> dict[str, Any]:
    """What a tool result's input says the call did: its activities and the paths it read and wrote."""
    tool = str(attributes.get("tool_name") or "")
    tool_input, raw = _input(attributes)
    reads, writes = paths(tool, tool_input, raw)
    return {"activities": tuple(activities(tool, tool_input)), "reads": tuple(reads), "writes": tuple(writes)}


def _claude_origin(query_source: str) -> str:
    if query_source == "compact":
        return "auxiliary"
    return "main" if query_source in {"", "repl_main_thread", "sdk"} else "side"


def _claude(name: str, a: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if name == "user_prompt":
        yield {"kind": "prompt", "name": str(a.get("command_name") or "")}
    elif name == "api_request":
        source = str(a.get("query_source") or "")
        origin = _claude_origin(source)
        yield {
            "kind": "request",
            "model": str(a.get("model") or ""),
            "effort": str(a.get("effort") or ""),
            "origin": origin,
            "agent": str(a.get("agent.name") or (source if origin == "side" else "")),
            "detail": source,
            "seconds": _seconds(a.get("duration_ms")),
            "input": _number(a.get("input_tokens")),
            "output": _number(a.get("output_tokens")),
            "cache_read": _number(a.get("cache_read_tokens")),
            "cache_write": _number(a.get("cache_creation_tokens")),
            "cost": _cost(a.get("cost_usd")),
        }
    elif name == "tool_decision":
        yield {
            "kind": "decision",
            "name": str(a.get("tool_name") or ""),
            "ok": str(a.get("decision")) == "accept",
            "detail": str(a.get("source") or ""),
        }
    elif name == "tool_result":
        yield {
            "kind": "tool",
            "name": str(a.get("tool_name") or ""),
            "ok": _flag(a.get("success")),
            "seconds": _seconds(a.get("duration_ms")),
            **_call(a),
        }
    elif name == "skill_activated":
        yield {"kind": "skill", "name": str(a.get("skill.name") or "")}
    elif name == "compaction":
        yield {"kind": "compaction", "name": str(a.get("trigger") or "")}


def _codex(name: str, a: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if name == "codex.conversation_starts":
        yield {"kind": "start", "detail": str(a.get("originator") or ""), "model": str(a.get("model") or "")}
    elif name == "codex.user_prompt":
        yield {"kind": "prompt"}
    elif name == "codex.sse_event" and a.get("event.kind") == "response.completed":
        cached = _number(a.get("cached_token_count"))
        yield {
            "kind": "request",
            "model": str(a.get("model") or ""),
            "effort": str(a.get("model_reasoning_effort") or ""),
            "input": max(_number(a.get("input_token_count")) - cached, 0),
            "output": _number(a.get("output_token_count")),
            "cache_read": cached,
            "cache_write": _number(a.get("cache_write_token_count")),
            "reasoning": _number(a.get("reasoning_token_count")),
        }
    elif name == "codex.tool_decision":
        yield {
            "kind": "decision",
            "name": str(a.get("tool_name") or ""),
            "ok": str(a.get("decision")).startswith("approved"),
            "detail": str(a.get("source") or ""),
        }
    elif name == "codex.tool_result":
        agent = str(a.get("agent_name") or "")
        main = agent in _MAIN_AGENT
        yield {
            "kind": "tool",
            "name": str(a.get("tool_name") or ""),
            "ok": _flag(a.get("success")),
            "origin": "main" if main else "side",
            "agent": "" if main else agent,
            "seconds": _seconds(a.get("duration_ms")),
            **_call(a),
        }
    elif name == "codex.skill_invocation":
        yield {"kind": "skill", "name": str(a.get("skill.name") or "")}
    elif name == "codex.turn_cost" and _flag(a.get("turn.interrupted")):
        yield {"kind": "interrupt", "effort": str(a.get("reasoning_effort") or "")}


def _identity(attributes: dict[str, Any]) -> tuple[str, str, Callable[[str, dict[str, Any]], Iterator[dict]]]:
    if str(attributes.get("event.name") or "").startswith("codex."):
        return CODEX, str(attributes.get("conversation.id") or ""), _codex
    return CLAUDE_CODE, str(attributes.get("session.id") or ""), _claude


def redactor(setting: str) -> Callable[[str], str]:
    """The filter a `module:function` setting names, which a stored shell command passes through."""
    module, _, name = setting.partition(":")
    if not module or not name:
        raise ValueError(f"redactor {setting!r}: expected module:function")
    try:
        found = getattr(importlib.import_module(module), name, None)
    except ImportError as error:
        raise ValueError(f"redactor {setting!r}: {error}") from error
    if not callable(found):
        raise ValueError(f"redactor {setting!r} names no function (expected module:function)")
    return found


def _stored_command(attributes: dict[str, Any], redact: Callable[[str], str] | None) -> str:
    """A shell call's command as it may be kept: heredoc bodies as length and hash, the rest through `redact`.

    Empty without a redactor, for a tool that is not a shell, or when `redact` fails: a command is kept only once the
    filter has seen it."""
    if redact is None or str(attributes.get("tool_name")) not in SHELLS:
        return ""
    try:
        return redact(elide_heredocs(_command(_input(attributes)[0])))
    except Exception:
        log.exception("command redactor failed; the command is not stored")
        return ""


def signals(payload: dict[str, Any], redact: Callable[[str], str] | None = None) -> list[Signal]:
    """The signals in an OTLP logs payload, in the order it carries them; records of events not read are skipped.

    A Claude Code shell result keeps its command, passed through `redact`; with none, no command is kept."""
    found: list[Signal] = []
    for resource_branch, record in _records(payload):
        a = _attributes(record)
        harness, session, read = _identity(a)
        at = _epoch(a.get("event.timestamp"))
        if not session or at is None:
            continue
        name = str(a.get("event.name") or "").removeprefix("claude_code.")
        branch = resource_branch or (str(a.get(BRANCH)) if a.get(BRANCH) else None)
        identity = a.get("event.sequence") if harness == CLAUDE_CODE else a.get("call_id")
        key = f"{harness}:{session}:{name}:{identity}:{a.get('event.timestamp')}"
        for fields in read(name, a):
            if fields["kind"] == "tool" and harness == CLAUDE_CODE:
                fields = {**fields, "command": _stored_command(a, redact)}
            found.append(
                Signal(harness, session, time=at, key=key, branch=branch, captured=harness == CLAUDE_CODE, **fields)
            )
        if str(a.get("tool_name")) in SHELLS and (switch := _SWITCH.search(_command(_input(a)[0]))):
            found.append(
                Signal(
                    harness,
                    session,
                    "branch",
                    at,
                    f"{key}:branch",
                    branch,
                    name=switch[2],
                    captured=harness == CLAUDE_CODE,
                )
            )
    return found


_FIELDS = {f.name for f in fields(Signal)}
_LISTS = ("activities", "reads", "writes")


def _signal(stored: dict[str, Any]) -> Signal:
    """A signal as the event log stored it, whose tuples came back as lists."""
    kept = {k: v for k, v in stored.items() if k in _FIELDS}
    kept.setdefault("captured", kept.get("harness") == CLAUDE_CODE)  # rows stored before the mark was kept
    return Signal(**{k: tuple(v) if k in _LISTS else v for k, v in kept.items()})


class TelemetryLog:
    """The signals both harnesses' exports gave, kept in the event log's `telemetry:signals` stream.

    The stream is private to the instance: it has no entry in `EVENT_STREAMS` and no consumer tails it.

    `publish` appends each signal under its `key`, so a replayed export adds nothing, and fails open like the log: a
    database that cannot be opened drops the signals, never the export. `read` returns the signals no older than
    `since`, in the order they were published; it polls the stream's tail since its last read and holds what it
    read, dropping what is older than `keep` seconds before the newest signal it holds (the log prunes its own rows
    by its `event_log_retention_days`), so a read costs only what was published since the last one.
    """

    STREAM = "telemetry:signals"

    def __init__(self, log: EventLog, keep: float = 7 * 86400.0) -> None:
        self._log = log
        self._tail = Tail(log, self.STREAM, batch=5000)
        self._keep = keep
        self._held: list[Signal] = []
        self._lock = threading.Lock()

    def publish(self, found: Iterable[Signal]) -> None:
        for signal in found:
            self._log.append(self.STREAM, asdict(signal), event_id=signal.key)

    def read(self, since: float = 0.0) -> list[Signal]:
        """The held signals from `since` on; raises when the database cannot be read."""
        with self._lock:
            while entries := self._tail.poll():
                self._held += [_signal(entry.fields) for entry in entries]
                if len(entries) < self._tail.batch:
                    break
            if self._held:
                floor = max(s.time for s in self._held) - self._keep
                self._held = [s for s in self._held if s.time >= floor]
            return [s for s in self._held if s.time >= since]
