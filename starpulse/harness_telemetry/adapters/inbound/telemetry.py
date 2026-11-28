"""The signals session and slice health fold, read from Claude Code's OTLP/HTTP log exports.

An export is `resourceLogs[].scopeLogs[].logRecords[]`, each record a bag of typed attributes. A record becomes one
`Signal`, keyed by Claude Code's `session.id` and ordered by its `event.timestamp`.

What a signal keeps is a count, a duration, a model or effort name, a tool, skill or decision name and the branch;
the tool output and account fields every such record also carries are never read; a prompt's text is read only
for its origin label and, when the instance configures a labeller, sent to it for its intent label, and never kept; a
reply's text is read only for whether its first sentence asks, and never kept; and
a shell tool's input is read only for the `git switch` or `git checkout` ref it names, which is kept as a `branch`
signal.

Records read: `user_prompt`, `api_request`, `tool_decision`, `tool_result`, `hook_execution_complete` (inside a turn), `skill_activated`, `assistant_response`, `compaction`.
"""

import importlib
import json
import logging
import re
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, fields
from typing import TYPE_CHECKING, Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import CLAUDE_CODE, Signal, claim_key, claimed, main_thread_source
from starpulse.harness_telemetry.adapters.inbound.otlp import BRANCH, _attributes, _epoch, _records
from starpulse.harness_telemetry.model.activity import SHELLS, activities, elide_heredocs, paths, writes_file
from starpulse.harness_telemetry.model.intent_classification import intent_label

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from starpulse.flow_metrics.adapters.outbound.session_ledger import SessionLedger
lazy from starpulse.harness_telemetry.adapters.outbound import step_seconds

__all__ = ["CLAUDE_CODE", "Signal", "TelemetryLog", "held", "redactor", "signals", "telemetry_log"]

log = logging.getLogger(__name__)


class ClaimUnreadable(Exception):
    """The stored claims could not be read, which is not the same as a session having claimed nothing."""

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
    """A tool call's `tool_input` as the export gave it, parsed when it is a JSON object, and its raw text."""
    if (raw := attributes.get("tool_input")) is None:
        return {}, ""
    try:
        parsed = json.loads(str(raw))
    except ValueError:
        return {}, str(raw)
    if not isinstance(parsed, dict):
        return {}, str(raw)
    if full := _full_command(attributes):
        parsed = {**parsed, "command": full}
    return parsed, str(raw)


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
    command = tool_input.get("command")
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


def _named(text: Any, origins: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    opening = str(text or "").lstrip()
    return next((name for name, prefixes in origins if opening.startswith(prefixes)), "")


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
            "agent_id": str(a.get("agent_id") or ""),
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
    for resource_branch, resource_eval, entrypoint, record in _records(payload, reading.eval_attribute):
        a = _attributes(record)
        session = str(a.get("session.id") or "")
        at = _epoch(a.get("event.timestamp"))
        if not session or at is None:
            continue
        name = str(a.get("event.name") or "").removeprefix("claude_code.")
        branch = resource_branch or (str(a.get(BRANCH)) if a.get(BRANCH) else None)
        record_eval = a.get(reading.eval_attribute) if reading.eval_attribute else None
        purpose = resource_eval or (str(record_eval) if record_eval else "")
        key = f"{CLAUDE_CODE}:{session}:{name}:{a.get('event.sequence')}:{a.get('event.timestamp')}"
        turn = str(a.get("prompt.id") or "")
        for parts in _claude(name, a):
            if parts["kind"] == "tool":
                parts = {**parts, "command": _stored_command(a, redact)}
            elif parts["kind"] == "prompt":
                origin = _label(a.get("prompt"), reading.injected_openings)
                intent = (
                    intent_label(reading.labeller, str(a["prompt"])) if reading.labeller and origin == "human" else ""
                )
                parts = {
                    **parts,
                    "detail": origin
                    if origin == "injected"
                    else _named(a.get("prompt"), reading.session_origins) or origin,
                    "label": intent,
                }
            found.append(
                Signal(
                    CLAUDE_CODE,
                    session,
                    time=at,
                    key=key,
                    branch=branch,
                    turn=turn,
                    eval=purpose,
                    entrypoint=entrypoint,
                    **parts,
                )
            )
        if str(a.get("tool_name")) in SHELLS and (switch := _SWITCH.search(_command(_input(a)[0]))):
            found.append(
                Signal(
                    CLAUDE_CODE,
                    session,
                    "branch",
                    at,
                    f"{key}:branch",
                    branch,
                    name=switch[2],
                    turn=turn,
                    eval=purpose,
                    entrypoint=entrypoint,
                )
            )
        if name == "tool_result" and (text := _named_text(a)):
            if (task := claimed(text, reading.claims, keys)) is not None:
                found.append(
                    Signal(
                        CLAUDE_CODE,
                        session,
                        "claim",
                        at,
                        claim_key(key),
                        branch,
                        name=task,
                        turn=turn,
                        eval=purpose,
                        entrypoint=entrypoint,
                    )
                )
            if reading.completion_call and str(a.get("tool_name")) in SHELLS and reading.completion_call.search(text):
                found.append(
                    Signal(
                        CLAUDE_CODE,
                        session,
                        "deliver",
                        at,
                        f"{key}:deliver",
                        branch,
                        turn=turn,
                        eval=purpose,
                        entrypoint=entrypoint,
                    )
                )
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
        "entrypoint",
    )
)


def stored_signal(stored: dict[str, Any]) -> Signal:
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
    """`found` as the table gives it back once stored: the first signal of each key, read from its stored fields, so a
    replayed record counts once and a shell command that writes a file carries `shell_write`."""
    first: dict[str, Signal] = {}
    for signal in found:
        first.setdefault(signal.key, signal)
    return [stored_signal(asdict(signal)) for signal in first.values()]


class TelemetryLog:
    """Where the adapters put the signals an export gave: each export advances its sessions' folds in the event log
    (`SessionLedger`), and no signal is kept past it.

    `publish` fails open like the log: a store that cannot be written drops the export's signals, never the export. A
    replayed export changes no fold. `keys` and `analytics` are the ones the folds are made under.
    """

    def __init__(self, log: EventLog, keys: TaskKeys | None = None, analytics: Analytics | None = None) -> None:
        self._events = log
        self._keys = keys
        self._analytics = analytics

    def publish(self, found: Iterable[Signal]) -> None:

        try:
            step_seconds.unassigned(self._ledger().apply(found))
        except SQLAlchemyError:
            log.warning("session folds unwritable; dropping signals", exc_info=True)

    def close(self, harness: str, session: str) -> None:
        """Store the case `session` left open as an unfinished Trace; fails open like `publish`."""
        try:
            self._ledger().close(harness, session)
        except SQLAlchemyError:
            log.warning("session ledger unwritable; its open case is not stored", exc_info=True)

    def last_claim(self, harness: str, session: str) -> tuple[str, float] | None:
        """The task `session` last claimed in an export and when, or None when it claimed none.

        Raises `ClaimUnreadable` when the folds cannot be read, so a failed read is not taken for no claim."""

        try:
            return self._ledger().last_claim(harness, session)
        except SQLAlchemyError:
            log.warning("session folds unreadable; no claim recalled", exc_info=True)
            raise ClaimUnreadable(session) from None

    def _ledger(self):

        return SessionLedger(self._events, self._keys, self._analytics)


def telemetry_log(log: EventLog, keys: TaskKeys | None = None, analytics: Analytics | None = None) -> TelemetryLog:
    """The `TelemetryLog` of the event log `log`, folding under `keys` and `analytics`."""
    return TelemetryLog(log, keys, analytics)
