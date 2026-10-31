"""The signals session and slice health fold, read from Claude Code's and Codex's OTLP/HTTP log exports.

An export is `resourceLogs[].scopeLogs[].logRecords[]`, each record a bag of typed attributes. A record becomes one
`Signal`, keyed by the harness's own session id (`session.id` for Claude Code, `conversation.id` for Codex) and ordered
by its `event.timestamp`. Codex names its event in the `event.name` attribute, which wins over the log record's own
`eventName`, since the attribute is what the exporter sets.

What a signal keeps is a count, a duration, a model or effort name, a tool, skill or decision name and the branch;
the tool output and account fields every such record also carries are never read; a prompt's text is read only
for its origin label and, when the instance configures a labeller, sent to it for its intent label, and never kept; a
reply's text is read only for whether its first sentence asks, and never kept; and
a shell tool's input is read only for the `git switch` or `git checkout` ref it names, which is kept as a `branch`
signal.

| harness | records read |
|---|---|
| Claude Code | `user_prompt`, `api_request`, `tool_decision`, `tool_result`, `hook_execution_complete` (inside a turn), `skill_activated`, `assistant_response`, `compaction` |
| Codex | `codex.conversation_starts`, `codex.user_prompt`, `codex.sse_event` (`response.completed`), `codex.tool_decision`, `codex.tool_result`, `codex.skill_invocation`, `codex.turn_cost` (an interrupted turn) |
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, fields
from typing import TYPE_CHECKING, Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import CLAUDE_CODE, CODEX, Signal, claim_key, claimed, main_thread_source
from starpulse.harness_telemetry.model.activity import SHELLS, activities, elide_heredocs, paths, writes_file
from starpulse.harness_telemetry.model.intent_classification import intent_label
from starpulse.harness_telemetry.adapters.outbound.loki import LokiSignals
from starpulse.harness_telemetry.adapters.inbound.otlp import BRANCH, _attributes, _epoch, _records

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog

__all__ = ["CLAUDE_CODE", "CODEX", "Signal", "TelemetryLog", "held", "redactor", "signals", "telemetry_log"]

log = logging.getLogger(__name__)

#: Where Codex runs its main agent; a tool result from any other agent path is a subagent's.
_MAIN_AGENT = {"", "/root"}
#: `git switch` or `git checkout`, its flags, then the ref it names (never a `--` pathspec).
_SWITCH = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:switch|checkout)\s+((?:-(?!-\s)[\w-]+\s+)*)([^\s;&|<>-][^\s;&|<>]*)")


def _number(value: Any) -> int:
    try:
        return max(int(float(str(value))), 0)
    except ValueError, OverflowError:
        return 0


def _seconds(value: Any) -> float:
    return _number(value) / 1000


def _flag(value: Any) -> bool:
    return str(value).lower() == "true"


def _skill(attributes: dict[str, Any]) -> str:
    """The bare skill name: a plugin skill arrives as `plugin:skill`, and the analytics config keys on the bare one."""
    return str(attributes.get("skill.name") or "").rpartition(":")[2]


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
        if not isinstance(parsed, dict):
            return {}, str(raw)
        if full := _full_command(attributes):
            parsed = {**parsed, "command": full}
        return parsed, str(raw)
    return {}, ""


def _full_command(attributes: dict[str, Any]) -> str:
    """The untruncated shell command of a Claude Code tool result: its `tool_parameters.full_command`, where
    `tool_input` caps each string over 512 characters. Empty when the export carries none."""
    try:
        parameters = json.loads(str(attributes.get("tool_parameters")))
    except ValueError:
        return ""
    full = parameters.get("full_command") if isinstance(parameters, dict) else None
    return full if isinstance(full, str) else ""


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


def _label(text: Any, injected: tuple[str, ...]) -> str:
    """`injected` for a prompt whose opening is one of `injected`, `human` for any other, empty when the export
    carried no text (prompt logging off, or the exporter's `<REDACTED>`). Only the label leaves this function."""
    opening = str(text or "").lstrip()
    if not opening or opening == "<REDACTED>":
        return ""
    return "injected" if opening.startswith(injected) else "human"


# A reply asks the operator when its first sentence ends in a question mark.
_OPENING_QUESTION = re.compile(r"(?:[^.!?\n]|[.!?](?!\s))*\?(?:\s|$)")


def _asks(text: Any) -> str:
    """`asks` for a reply whose first sentence ends in a question mark, empty for any other, or when the export
    carried no text (reply logging off, or the exporter's `<REDACTED>`). Only the mark leaves this function."""
    return "asks" if _OPENING_QUESTION.match(str(text or "").strip()) else ""


def _claude_origin(query_source: str) -> str:
    if query_source == "compact":
        return "auxiliary"
    return "main" if main_thread_source(query_source) in {"", "repl_main_thread", "sdk"} else "side"


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
    elif name == "hook_execution_complete" and a.get("prompt.id"):
        yield {"kind": "hook", "name": str(a.get("hook_name") or ""), "seconds": _seconds(a.get("total_duration_ms"))}
    elif name == "skill_activated":
        yield {"kind": "skill", "name": _skill(a)}
    elif name == "assistant_response":
        source = str(a.get("query_source") or "")
        yield {"kind": "reply", "origin": _claude_origin(source), "detail": _asks(a.get("response"))}
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
        yield {"kind": "skill", "name": _skill(a)}
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


def _named_text(attributes: dict[str, Any]) -> str:
    """The text of a Claude Code tool result that may name a task or deliver one: a shell command, or the arguments
    of a `Skill` call. Read for a match and dropped; only the task key a claim matched is ever kept."""
    tool = str(attributes.get("tool_name") or "")
    tool_input = _input(attributes)[0]
    if tool in SHELLS:
        return _command(tool_input)
    args = tool_input.get("args") if tool == "Skill" else None
    return args if isinstance(args, str) else ""


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


def signals(
    payload: dict[str, Any],
    redact: Callable[[str], str] | None = None,
    *,
    analytics: Analytics | None = None,
    keys: TaskKeys | None = None,
) -> list[Signal]:
    """The signals in an OTLP logs payload, in the order it carries them; records of events not read are skipped.

    A Claude Code shell result keeps its command, passed through `redact`; with none, no command is kept."""
    reading = analytics or Analytics()
    found: list[Signal] = []
    for resource_branch, resource_eval, record in _records(payload, reading.eval_attribute):
        a = _attributes(record)
        harness, session, read = _identity(a)
        at = _epoch(a.get("event.timestamp"))
        if not session or at is None:
            continue
        name = str(a.get("event.name") or "").removeprefix("claude_code.")
        branch = resource_branch or (str(a.get(BRANCH)) if a.get(BRANCH) else None)
        record_eval = a.get(reading.eval_attribute) if reading.eval_attribute else None
        purpose = resource_eval or (str(record_eval) if record_eval else "")
        identity = a.get("event.sequence") if harness == CLAUDE_CODE else a.get("call_id")
        key = f"{harness}:{session}:{name}:{identity}:{a.get('event.timestamp')}"
        turn = str(a.get("prompt.id") or "") if harness == CLAUDE_CODE else ""
        for fields in read(name, a):
            if fields["kind"] == "tool" and harness == CLAUDE_CODE:
                fields = {**fields, "command": _stored_command(a, redact)}
            elif fields["kind"] == "prompt" and harness == CLAUDE_CODE:
                origin = _label(a.get("prompt"), reading.injected_openings)
                intent = (
                    intent_label(reading.labeller, str(a["prompt"])) if reading.labeller and origin == "human" else ""
                )
                fields = {**fields, "detail": origin, "label": intent}
            found.append(
                Signal(
                    harness,
                    session,
                    time=at,
                    key=key,
                    branch=branch,
                    captured=harness == CLAUDE_CODE,
                    turn=turn,
                    eval=purpose,
                    **fields,
                )
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
                    turn=turn,
                    eval=purpose,
                )
            )
        if harness == CLAUDE_CODE and name == "tool_result" and (text := _named_text(a)):
            if (task := claimed(text, reading.claims, keys)) is not None:
                found.append(
                    Signal(harness, session, "claim", at, claim_key(key), branch, name=task, turn=turn, eval=purpose)
                )
            if reading.completion_call and str(a.get("tool_name")) in SHELLS and reading.completion_call.search(text):
                found.append(Signal(harness, session, "deliver", at, f"{key}:deliver", branch, turn=turn, eval=purpose))
    return found


_FIELDS = {f.name for f in fields(Signal)}
_LISTS = ("activities", "reads", "writes")
# Fields whose few distinct values repeat across the held history: one string object each, not one per signal.
_SHARED = frozenset(
    (
        "harness",
        "session",
        "kind",
        "branch",
        "name",
        "model",
        "effort",
        "origin",
        "agent",
        "detail",
        "turn",
        "label",
        "eval",
    )
)


def _signal(stored: dict[str, Any]) -> Signal:
    """A signal as the event log stored it, whose tuples came back as lists."""
    kept = {k: v for k, v in stored.items() if k in _FIELDS}
    kept.setdefault("captured", kept.get("harness") == CLAUDE_CODE)  # rows stored before the mark was kept
    # Read from the stored command, so a row stored before the mark existed carries it too.
    kept["shell_write"] = (
        kept.get("kind") == "tool" and kept.get("name") in SHELLS and writes_file(kept.get("command", ""))
    )
    return Signal(**{k: _shared(k, v) for k, v in kept.items()})


def _shared(field: str, value: Any) -> Any:
    """`value` of `field` with its strings interned, a list field as a tuple."""
    if field in _LISTS:
        return tuple(sys.intern(item) for item in value)
    return sys.intern(value) if field in _SHARED and isinstance(value, str) else value


def held(found: Iterable[Signal]) -> list[Signal]:
    """`found` as `TelemetryLog.read` gives it back once published: the first signal of each key, read from its stored
    fields, so a replayed record counts once and a shell command that writes a file carries `shell_write`."""
    first: dict[str, Signal] = {}
    for signal in found:
        first.setdefault(signal.key, signal)
    return [_signal(asdict(signal)) for signal in first.values()]


KEEP_S = 8 * 86400.0  # a day past the views' default 168 h window: the oldest held signal never lies inside it


class TelemetryLog:
    """The signals both harnesses' exports gave, kept in Loki when the config names one, else in the event log's
    `telemetry:signals` stream.

    The stream is private to the instance: it has no entry in `EVENT_STREAMS` and no consumer tails it.

    `publish` stores each signal under its `key`, so a replayed export adds nothing, and fails open like the log: a
    database that cannot be opened drops the signals, never the export. `read` returns the signals no older than
    `since`, in the order they were published; it polls the store since its last read and holds what it read,
    dropping what is older than `keep` seconds before the newest signal it holds (the log prunes its own rows by its
    `event_log_retention_days`, Loki's stream by its retention rule). Every read returns references into that one
    held snapshot, so concurrent analytics requests cost a list of pointers each, never a second hydration of the
    stream. A Loki store keeps a replayed signal's second line, which `read` drops by key.
    """

    STREAM = "telemetry:signals"

    def __init__(self, log: EventLog | None, keep: float = KEEP_S, *, loki: LokiSignals | None = None) -> None:
        self._log = log
        self._loki = loki
        self._keep = keep
        self._held: list[Signal] = []
        self._keys: set[str] = set()
        self._lock = threading.Lock()
        if loki is None:
            assert log is not None  # without Loki the event log is the store
            from starpulse.event_log.event_log import Tail  # noqa: PLC0415 - the database stack loads when a log opens

            self._tail = Tail.replay(log, self.STREAM, batch=5000)
        self._stamp = time.time_ns() - int(keep * 1e9)

    def publish(self, found: Iterable[Signal]) -> None:
        if self._loki is not None:
            self._loki.push(asdict(signal) for signal in found)
            return
        for signal in found:
            self._log.publish(self.STREAM, asdict(signal), event_id=signal.key)

    def _poll(self) -> list[Signal]:
        """The stored signals since the last poll."""
        if self._loki is None:
            polled = []
            while entries := self._tail.poll():
                polled += [_signal(entry.fields) for entry in entries]
                if len(entries) < self._tail.batch:
                    break
            return polled
        new = []
        for page in self._loki.pages(self._stamp):
            if page:
                self._stamp = page[-1][0]
            for _, row in page:
                if row.get("key") not in self._keys:
                    self._keys.add(row["key"])
                    new.append(_signal(row))
        return new

    def read(self, since: float = 0.0) -> list[Signal]:
        """The held signals from `since` on; raises when the store cannot be read."""
        with self._lock:
            polled = self._poll()
            if polled:  # the hold only changes when a poll brings signals: no rescan of it per request
                self._held += polled
                floor = max(s.time for s in self._held) - self._keep
                self._held = [s for s in self._held if s.time >= floor]
                self._keys.intersection_update(s.key for s in self._held)
            return [s for s in self._held if s.time >= since]


def telemetry_log(url: str | None, log: EventLog | None) -> TelemetryLog:
    """The `TelemetryLog` of `telemetry_loki_url`, else of the event log `log`."""
    return TelemetryLog(log, loki=LokiSignals(url) if url else None)
