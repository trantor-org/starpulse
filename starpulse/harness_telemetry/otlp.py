"""Claude Code's OTLP/HTTP JSON log events, read into the ones a machine moves on.

The export is `resourceLogs[].scopeLogs[].logRecords[]`, each record a bag of
typed attributes (`stringValue`, `intValue` as a string, `boolValue`). Only
`user_prompt`, `tool_result`, `skill_activated` and `assistant_response` (bare or
`claude_code.`-prefixed) are kept, and of each only what an adapter keys on: the
account fields, prompt and reply text every such record also carries are never
read into a `LogEvent`. The branch is the resource's `vcs.ref.head.name`, which a
launch sets through `OTEL_RESOURCE_ATTRIBUTES`; the export names none itself.

`receiver` serves the export over OTLP/HTTP:

POST /v1/logs   an OTLP/HTTP logs export as JSON (`http/json`), plain or gzipped. Answers 200 `{}`
                whatever the consumer does with it: a consumer fault is logged and the stream stays
                silent, and a retry would only replay it. A body that is not JSON is 400, a protobuf
                body 415, a body over 8 MiB 413.
GET  /healthz   200 `ok`
"""

from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from typing import Any

__all__ = [
    "ASSISTANT_RESPONSE",
    "BRANCH",
    "SKILL_ACTIVATED",
    "TOOL_RESULT",
    "USER_PROMPT",
    "LogEvent",
    "parse",
    "receiver",
]

log = logging.getLogger(__name__)

USER_PROMPT = "user_prompt"
TOOL_RESULT = "tool_result"
SKILL_ACTIVATED = "skill_activated"
ASSISTANT_RESPONSE = "assistant_response"
_KINDS = {
    spelling: kind
    for kind in (USER_PROMPT, TOOL_RESULT, SKILL_ACTIVATED, ASSISTANT_RESPONSE)
    for spelling in (kind, f"claude_code.{kind}")
}
BRANCH = "vcs.ref.head.name"
MAX_BODY = 8 * 1024 * 1024


@dataclass(frozen=True)
class LogEvent:
    """One kept log record. `skill` is set for a skill activation; the tool fields for a tool result.

    `time` is the record's `event.timestamp` in epoch seconds, and `branch` the export resource's
    `vcs.ref.head.name`; each is None when absent.
    """

    session: str
    sequence: int
    kind: str
    tool_name: str = ""
    tool_use_id: str = ""
    success: bool = False
    tool_input: dict[str, Any] = field(default_factory=dict)
    skill: str = ""
    time: float | None = None
    branch: str | None = None


def _value(wrapped: Any) -> Any:
    if not isinstance(wrapped, dict):
        return None
    for key in ("stringValue", "intValue", "boolValue", "doubleValue"):
        if key in wrapped:
            return wrapped[key]
    return None


def _attributes(record: dict[str, Any]) -> dict[str, Any]:
    attributes = record.get("attributes")
    if not isinstance(attributes, list):
        return {}
    return {a["key"]: _value(a.get("value")) for a in attributes if isinstance(a, dict) and "key" in a}


def _records(payload: dict[str, Any]) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """Each log record with the branch its resource names."""
    resources = payload.get("resourceLogs")
    for resource in resources if isinstance(resources, list) else ():
        scopes = resource.get("scopeLogs") if isinstance(resource, dict) else None
        described = resource.get("resource") if isinstance(resource, dict) else None
        branch = _attributes(described).get(BRANCH) if isinstance(described, dict) else None
        for scope in scopes if isinstance(scopes, list) else ():
            records = scope.get("logRecords") if isinstance(scope, dict) else None
            for record in records if isinstance(records, list) else ():
                if isinstance(record, dict):
                    yield (str(branch) if branch else None), record


def _epoch(timestamp: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(timestamp)).timestamp()
    except ValueError:
        return None


def _tool_input(raw: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _kind(record: dict[str, Any], attributes: dict[str, Any]) -> str | None:
    name = attributes.get("event.name") or _value(record.get("body"))
    return _KINDS.get(str(name))


def parse(payload: dict[str, Any]) -> list[LogEvent]:
    """The prompts, tool results, skill activations and replies in an OTLP logs payload, in the order it carries them."""
    events = []
    for branch, record in _records(payload):
        attributes = _attributes(record)
        kind = _kind(record, attributes)
        session = attributes.get("session.id")
        sequence = attributes.get("event.sequence")
        if kind is None or not session or not str(sequence).isdigit():
            continue
        events.append(
            LogEvent(
                session=str(session),
                sequence=int(str(sequence)),
                kind=kind,
                tool_name=str(attributes.get("tool_name") or ""),
                tool_use_id=str(attributes.get("tool_use_id") or ""),
                success=str(attributes.get("success")).lower() == "true",
                tool_input=_tool_input(attributes.get("tool_input")),
                skill=str(attributes.get("skill.name") or ""),
                time=_epoch(attributes.get("event.timestamp")),
                branch=branch,
            )
        )
    return events


def receiver(
    ingest: Callable[[list[LogEvent]], None], on_export: Callable[[dict[str, Any]], object] | None = None
) -> type[BaseHTTPRequestHandler]:
    """A request handler that parses each logs export and hands its events to `ingest`, one call per POST.

    `on_export`, when given, is called with the decoded export itself, for a consumer that reads more than `ingest`'s
    events; one that raises is logged and the export is still answered and ingested."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: bytes = b"{}", content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)  # pragma: no mutate: names are case-insensitive
            self.send_header("Content-Length", str(len(body)))  # pragma: no mutate: names are case-insensitive
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._reply(200, b"ok", "text/plain")
            else:
                self._reply(404)

        def do_POST(self) -> None:
            if self.path != "/v1/logs":
                self._reply(404)
                return
            declared = self.headers.get("Content-Type", "")  # pragma: no mutate: case-insensitive; any non-json default
            if "json" not in declared:
                self._reply(415, b'{"error": "send OTLP as json: set encoding = \\"json\\" on the exporter"}')
                return
            length = int(self.headers.get("Content-Length") or 0)  # pragma: no mutate: names are case-insensitive
            if length > MAX_BODY:
                self._reply(413)
                return
            raw = self.rfile.read(length)
            try:
                if self.headers.get("Content-Encoding") == "gzip":  # pragma: no mutate: names are case-insensitive
                    raw = gzip.decompress(raw)
                payload: Any = json.loads(raw)
                events = parse(payload) if isinstance(payload, dict) else []
            except OSError, ValueError:
                self._reply(400)
                return
            if on_export is not None and isinstance(payload, dict):
                try:
                    on_export(payload)
                except Exception:
                    log.exception("export consumer failed on an export of %d events", len(events))
            try:
                ingest(events)
            except Exception:
                log.exception("consumer failed on a batch of %d events", len(events))
            self._reply(200)

        def log_message(self, format: str, *args: Any) -> None:
            log.debug(format, *args)

    return Handler
