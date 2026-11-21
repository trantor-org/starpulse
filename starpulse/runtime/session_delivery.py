"""The bridge's delivery route to Claude Code sessions: a consumer whose session registered how to reach it is notified.

The composition root joins what two sibling contexts own: the bridge's waiting events and the sessions' registrations
and notifier. Each event becomes one line, with the angle brackets and line breaks of its values removed so a value
cannot close the envelope the notifier wraps it in or span lines.

A move of the session's task to a finished lane never reaches the session: posting it would start a turn and keep an
ending session busy, and resuming an exited one would revive it. A move to a lane `[bridge] end_lanes` names runs the
`[bridge] end` command once per task in the batch, after any line is posted: the session reaper's pass scoped to that
task, which ends its session once it is idle and keeps a busy one for the record write at its turn's end. The
registration of a session that ended is removed by `forget_ended`, which the subscriber runs after each lane move.

A move to any other lane whose writer `[bridge] quiet_moves` names for that lane is acked with no line too, and a batch
left with no line notifies nothing; `self` names the receiving session, matched through the same running-session records
as a claude.ai URL holder.

A failing-checks line names the skill that answers it, `skill=starpulse:fix-checks`, so the woken session fixes its
task's red check rather than waiting on the task actor's Review move, which only passing checks fire.

An `incident.<type>.<key>` event, which `starpulse incident open` publishes straight to NATS, is one line naming its owner task
and finder; one older than `INCIDENT_FRESH_S` is acked with no line.
"""

import json
import logging
import re
import time
from collections.abc import Callable, Collection, Mapping
from pathlib import Path

from starpulse.contracts.signals import CLAUDE_CODE
from starpulse.event_log import events as machine_events
from starpulse.event_log.claude_sessions import live_process, local_id, local_ids
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.adapters.inbound.telemetry import ClaimUnreadable, telemetry_log
from starpulse.harness_telemetry.adapters.outbound.session_exit import ExitWatch, watch_registered
from starpulse.harness_telemetry.model.harness import ended_id
from starpulse.event_log.lane_events import ARCHIVED, COMPLETED
from starpulse.bridge.delivery import Event, Route
from starpulse.bridge.subjects import INCIDENT
from starpulse.sessions.ports.notify import Line, Notifier, Registration
from starpulse.sessions.adapters.outbound.registry import Registry

logger = logging.getLogger(__name__)

_FIELDS = ("event", "lane", "task")
_UNSAFE = re.compile(r"[<>\r\n]+")
_VALUE_MAX = 120
_DATA_PAIRS = 20
_URL_HOLDER = re.compile(r"https_claude_ai_code_((?:session|cse)_\w+)")
#: An incident older than this is no news: a new consumer replays the last one of every key, so it is acked unannounced.
INCIDENT_FRESH_S = 6 * 3600
_FINISHED = frozenset({"done", COMPLETED, ARCHIVED})
SELF = "self"
#: The bundled skill each subject suffix wakes its session into.
_SKILLS = {".checks.failing": "starpulse:fix-checks"}


def _value(value: object) -> str:
    return _UNSAFE.sub(" ", str(value)).strip()[:_VALUE_MAX]


def _incident(event: Event) -> dict | None:
    if not event.subject.startswith(INCIDENT):
        return None
    try:
        body = json.loads(event.body)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _stale(event: Event) -> bool:
    body = _incident(event)
    at = body.get("at") if body else None
    return isinstance(at, (int, float)) and time.time() - at > INCIDENT_FRESH_S


def _incident_line(event: Event, body: dict) -> Line:
    pairs = [f"{key}={_value(body[key])}" for key in ("task", "finder") if body.get(key)]
    parts = pairs + [f"({_value(body.get('at', ''))})"]
    return Line(event.subject, f"{event.subject}: {' '.join(parts)}")


def line_for(event: Event) -> Line:
    """`<subject>: <event> <task> <data> (<event id>)`, from the entry the bridge published; an incident, which
    `starpulse incident open` publishes to NATS directly, reads `<subject>: task=<owner task> finder=<session> (<at>)`."""
    if (incident := _incident(event)) is not None:
        return _incident_line(event, incident)
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
    pairs += [("skill", skill) for suffix, skill in _SKILLS.items() if event.subject.endswith(suffix)]
    parts = [f"{_value(key)}={_value(value)}" for key, value in pairs] + [f"({_value(event_id)})"]
    return Line(event.subject, f"{event.subject}: {' '.join(parts)}")


def _moved_fields(event: Event) -> dict | None:
    if not event.subject.endswith(".moved"):
        return None
    try:
        fields = json.loads(event.body)["fields"]
    except (ValueError, KeyError, TypeError):
        return None
    return fields if isinstance(fields, dict) else None


def _ended_tasks(events: list[Event], lanes: Collection[str]) -> list[str]:
    moved = (_moved_fields(event) for event in events)
    return list(dict.fromkeys(str(f["task"]) for f in moved if f and f.get("lane") in lanes and f.get("task")))


def _quieted(event: Event, quiet: Mapping[str, Collection[str]], own: str, sessions: Path) -> bool:
    fields = _moved_fields(event)
    if fields is None:
        return False
    if fields.get("lane") in _FINISHED:
        return True
    writers = quiet.get(str(fields.get("lane")), ())
    if fields.get("actor") in writers:
        return True
    session = str(fields.get("session") or "")
    return SELF in writers and bool(own) and local_id(sessions, session) == own


def _holder_bridge(name: str) -> str:
    url = _URL_HOLDER.fullmatch(name)
    return url[1] if url else ""


def _local(sessions: Path, name: str) -> str:
    """The local session id a consumer named for a claude.ai URL holder resolves to; empty for any other name."""
    bridge = _holder_bridge(name)
    return local_id(sessions, f"https://claude.ai/code/{bridge}") if bridge else ""


def route(
    registry: Registry,
    notifier: Notifier,
    sessions: Path,
    quiet: Mapping[str, Collection[str]] | None = None,
    end: Callable[[str], None] | None = None,
    end_lanes: Collection[str] = (),
) -> Route:
    """A session with no registration has no route, so its events stay on its consumer. A consumer named for a
    claude.ai URL holder is the running session whose record in `sessions` carries that bridge id, which registered
    under its local id. `end` takes the id of each task a batch moved to a lane `end_lanes` names."""

    def registered(name: str) -> Registration | None:
        if found := registry.get(name):
            return found
        local = _local(sessions, name)
        return registry.get(local) if local else None

    def find(name: str):  # noqa: ANN202
        registration = registered(name)
        if registration is None:
            return None

        def deliver(events: list[Event]) -> bool:
            own = local_id(sessions, registration.session)
            lines = [line_for(event) for event in events if not _stale(event) and not _quieted(event, quiet or {}, own, sessions)]
            delivered = notifier.notify(registration, lines) if lines else True
            outcome = "quieted, nothing sent" if not lines else "delivered" if delivered else "not delivered"
            logger.info("session %s: %s %s", name, ", ".join(event.subject for event in events), outcome)
            if delivered and end:
                for task in _ended_tasks(events, end_lanes):
                    end(task)
            return delivered

        return deliver

    return find


def forget_ended(registry: Registry, alive: Callable[[str], str | None], sessions: Path) -> Callable[[Collection[str]], None]:
    """Remove the registration of every session that is neither running nor named by a consumer in `names`: nothing
    is delivered to it, and a session that returns registers again at its next prompt, by the `session_register` hook."""

    def forget(names: Collection[str]) -> None:
        wanted = set(names)
        wanted |= local_ids(sessions, [bridge for name in names if (bridge := _holder_bridge(name))])
        for key in registry.keys():
            if key not in wanted and not ((registration := registry.get(key)) and alive(registration.session)):
                registry.delete(key)

    return forget


def exit_watcher(log: EventLog, registry: Registry, sessions: Path) -> Callable[[], None]:
    """A sync that holds a process descriptor per registered session with a running process: when one exits, a clean
    exit, kill or crash alike, `SESSION_ENDED` lands on the harness machine, under the task the session last claimed."""
    telemetry = telemetry_log(log)

    def ended(session: str, pid: int) -> None:
        try:
            claim = telemetry.last_claim(CLAUDE_CODE, session)
        except ClaimUnreadable:
            claim = None  # the end is kept under the session as a run rather than lost
        task = claim[0] if claim else None
        machine_events.publish(
            "harness", "SESSION_ENDED", actor="claude-code", task=task, run=None if task else session,
            event_id=ended_id(session, pid), log=log,
        )

    watch = ExitWatch(ended)
    process_of = live_process(sessions)

    def sync() -> None:
        registered = (registration.session for key in registry.keys() if (registration := registry.get(key)))
        watch_registered(registered, process_of, watch.watch)

    return sync
