"""The bridge's delivery route to Claude Code sessions: a consumer whose session registered how to reach it is notified.

The composition root joins what two sibling contexts own: the bridge's waiting events and the sessions' registrations
and notifier. Each event becomes one line, with the angle brackets and line breaks of its values removed so a value
cannot close the envelope the notifier wraps it in or span lines.
"""

import json
import re
from pathlib import Path

from starpulse.board.adapters.session_activity import local_id
from starpulse.bridge.delivery import Event, Route
from starpulse.sessions.ports.notify import Line, Notifier, Registration
from starpulse.sessions.adapters.outbound.registry import Registry

_FIELDS = ("event", "lane", "task")
_UNSAFE = re.compile(r"[<>\r\n]+")
_VALUE_MAX = 120
_DATA_PAIRS = 20
_URL_HOLDER = re.compile(r"https_claude_ai_code_((?:session|cse)_\w+)")


def _value(value: object) -> str:
    return _UNSAFE.sub(" ", str(value)).strip()[:_VALUE_MAX]


def line_for(event: Event) -> Line:
    """`<subject>: <event> <task> <data> (<event id>)`, from the entry the bridge published."""
    try:
        body = json.loads(event.body)
        fields = body["fields"]
        event_id = body["event_id"]
    except (ValueError, KeyError, TypeError):
        return Line(event.subject, event.subject)
    if not isinstance(fields, dict):
        return Line(event.subject, event.subject)
    data = fields.get("data")
    pairs = [(key, fields[key]) for key in _FIELDS if fields.get(key)]
    given = [(key, value) for key, value in (data if isinstance(data, dict) else {}).items() if value is not None]
    pairs += given[:_DATA_PAIRS]
    parts = [f"{_value(key)}={_value(value)}" for key, value in pairs] + [f"({_value(event_id)})"]
    return Line(event.subject, f"{event.subject}: {' '.join(parts)}")


def route(registry: Registry, notifier: Notifier, sessions: Path) -> Route:
    """A session with no registration has no route, so its events stay on its consumer. A consumer named for a
    claude.ai URL holder is the running session whose record in `sessions` carries that bridge id, which registered
    under its local id."""

    def registered(name: str) -> Registration | None:
        if (found := registry.get(name)) or not (url := _URL_HOLDER.fullmatch(name)):
            return found
        local = local_id(sessions, f"https://claude.ai/code/{url[1]}")
        return registry.get(local) if local else None

    def find(name: str):  # noqa: ANN202
        registration = registered(name)
        if registration is None:
            return None
        return lambda events: notifier.notify(registration, [line_for(event) for event in events])

    return find
