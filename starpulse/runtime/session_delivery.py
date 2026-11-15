"""The bridge's delivery route to Claude Code sessions: a consumer whose session registered how to reach it is notified.

The composition root joins what two sibling contexts own: the bridge's waiting events and the sessions' registrations
and notifier. Each event becomes one line, with the angle brackets and line breaks of its values removed so a value
cannot close the envelope the notifier wraps it in or span lines.

A move of the session's task to a finished lane never reaches the session: posting it would start a turn and keep an
ending session busy, and resuming an exited one would revive it. The move rewrites the task's board file, which starts
the session reaper's pass that ends the idle session.

A move to any other lane whose writer `[bridge] quiet_moves` names for that lane is acked with no line too, and a batch
left with no line notifies nothing; `self` names the receiving session, matched through the same running-session records
as a claude.ai URL holder.
"""

import json
import re
from collections.abc import Collection, Mapping
from pathlib import Path

from starpulse.board.adapters.session_activity import local_id
from starpulse.event_log.lane_events import ARCHIVED, COMPLETED
from starpulse.bridge.delivery import Event, Route
from starpulse.sessions.ports.notify import Line, Notifier, Registration
from starpulse.sessions.adapters.outbound.registry import Registry

_FIELDS = ("event", "lane", "task")
_UNSAFE = re.compile(r"[<>\r\n]+")
_VALUE_MAX = 120
_DATA_PAIRS = 20
_URL_HOLDER = re.compile(r"https_claude_ai_code_((?:session|cse)_\w+)")
_FINISHED = frozenset({"done", COMPLETED, ARCHIVED})
SELF = "self"


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


def _quieted(event: Event, quiet: Mapping[str, Collection[str]], own: str, sessions: Path) -> bool:
    if not event.subject.endswith(".moved"):
        return False
    try:
        fields = json.loads(event.body)["fields"]
    except (ValueError, KeyError, TypeError):
        return False
    if not isinstance(fields, dict):
        return False
    if fields.get("lane") in _FINISHED:
        return True
    writers = quiet.get(str(fields.get("lane")), ())
    if fields.get("actor") in writers:
        return True
    session = str(fields.get("session") or "")
    return SELF in writers and bool(own) and local_id(sessions, session) == own


def route(
    registry: Registry, notifier: Notifier, sessions: Path, quiet: Mapping[str, Collection[str]] | None = None
) -> Route:
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

        def deliver(events: list[Event]) -> bool:
            own = local_id(sessions, registration.session)
            lines = [line_for(event) for event in events if not _quieted(event, quiet or {}, own, sessions)]
            return notifier.notify(registration, lines) if lines else True

        return deliver

    return find
