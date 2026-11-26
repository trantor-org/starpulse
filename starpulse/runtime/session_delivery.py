"""The bridge's delivery route to Claude Code sessions: a consumer whose session registered how to reach it is notified.

The composition root joins what two sibling contexts own: the bridge's waiting events and the sessions' registrations
and notifier. Each event becomes one line, with the angle brackets and line breaks of its values removed so a value
cannot close the envelope the notifier wraps it in or span lines.

A move of the session's task to a finished lane never reaches the session: posting it would start a turn and keep an
ending session busy, and resuming an exited one would revive it. The task actor ends the session (`[bridge] end`);
this route runs no end. The registration of a session that ended is removed by `forget_ended`, which the subscriber runs after each lane move.

A move to any other lane whose writer `[bridge] quiet_moves` names for that lane is acked with no line too, and a batch
left with no line notifies nothing; `self` names the receiving session, matched through the same running-session records
as a claude.ai URL holder.

An event the session already received is acked with no line: the server redelivers one whose ack was lost, and a
resume wake heard again would start a turn with nothing to do.

A failing-checks line names the skill that answers it, `skill=starpulse:fix-checks`, so the woken session fixes its
task's red check rather than waiting on the task actor's Review move, which only passing checks fire.

An `incident.<type>.<key>` event, which `starpulse incident open` publishes straight to NATS, is one line naming its owner task
and finder; one older than `INCIDENT_FRESH_S`, one whose owner task is done or archived, and one that names the
`parked` holders it woke (`--failing-pull`) for another consumer are acked with no line.

A pull request event judged at one head (`data.head`, the `ci` machine's CONFLICTED) is acked with no line once the
store holds a different head for that pull request: a push already answered it, and the bridge's lag or a consumer's
replay would otherwise wake the session to re-check a resolved conflict. A head the store does not know sends the line.
"""

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Collection, Mapping
from pathlib import Path

from starpulse.bridge.delivery import Event, Route
from starpulse.bridge.subjects import INCIDENT
from starpulse.event_log import events as machine_events
from starpulse.event_log.claude_sessions import live_process, local_id, local_ids
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.lane_events import ARCHIVED, COMPLETED
from starpulse.harness_telemetry.adapters.outbound.session_exit import ExitWatch, watch_registered
from starpulse.harness_telemetry.model.harness import ended_id
from starpulse.pulls.adapters.outbound.pull_requests import PULL_URL
from starpulse.sessions.adapters.outbound.registry import Registry
from starpulse.sessions.ports.notify import Line, Notifier, Registration

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
_SEEN_MAX = 256
#: Suffixes of a holder's wake that mean nothing once its task left In Progress.
_HOLDER_WAKES = ("holder_resume", "review_refused")
#: The bundled skill each subject suffix wakes its session into.
_SKILLS = {".checks.failing": "starpulse:fix-checks"}


def _value(value: object) -> str:
    """A value cut to `_VALUE_MAX` ends with a digest of the whole, so two long values sharing a head read differently."""
    text = _UNSAFE.sub(" ", str(value)).strip()
    if len(text) <= _VALUE_MAX:
        return text
    return f"{text[:_VALUE_MAX]}~{hashlib.sha256(text.encode()).hexdigest()[:6]}"


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


def _unaddressed(event: Event, name: str) -> bool:
    body = _incident(event)
    parked = body.get("parked") if body else None
    return isinstance(parked, list) and name not in parked


def _closed(event: Event, closed: Callable[[str], bool] | None) -> bool:
    body = _incident(event)
    owner = body.get("task") if body else None
    return bool(closed and isinstance(owner, str) and closed(owner))


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
    except ValueError, KeyError, TypeError:
        return Line(event.subject, event.subject)
    if not isinstance(fields, dict):
        return Line(event.subject, event.subject)
    data = fields.get("data")
    # a move's time tells two send-backs to one lane apart
    keys = (*_FIELDS, "time") if event.subject.endswith(".moved") else _FIELDS
    pairs = [(key, fields[key]) for key in keys if fields.get(key)]
    given = [(key, value) for key, value in (data if isinstance(data, dict) else {}).items() if value is not None]
    pairs += given[:_DATA_PAIRS]
    pairs += [("skill", skill) for suffix, skill in _SKILLS.items() if event.subject.endswith(suffix)]
    payload = f"{event.subject}: {' '.join(f'{_value(key)}={_value(value)}' for key, value in pairs)}"
    return Line(event.subject, f"{payload} ({_value(event_id)})", payload)


def _moved_fields(event: Event) -> dict | None:
    if not event.subject.endswith(".moved"):
        return None
    try:
        fields = json.loads(event.body)["fields"]
    except ValueError, KeyError, TypeError:
        return None
    return fields if isinstance(fields, dict) else None


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


def _passed(event: Event, head: Callable[[str, int], str | None] | None) -> bool:
    if head is None:
        return False
    try:
        body = json.loads(event.body)
        judged = body["fields"]["data"]["head"]
    except ValueError, KeyError, TypeError:
        return False
    url = PULL_URL.search(str(body.get("event_id", "")))
    stored = head(url[1], int(url[2])) if url and judged else None
    return bool(stored) and stored != judged


def _parked(event: Event, lane_of: Callable[[str], str | None] | None, working: Callable[[], str]) -> bool:
    parts = event.subject.split(".")
    if lane_of is None or parts[-1] not in _HOLDER_WAKES or len(parts) < 5:
        return False
    return lane_of(parts[-2]) not in (working(), "unknown")


def _held(event: Event, frozen: Callable[[str], bool] | None) -> bool:
    parts = event.subject.split(".")
    return bool(frozen and parts[-1] == "feedback" and len(parts) >= 5 and frozen(parts[-2]))


def _seen_key(event: Event) -> tuple[str, str] | None:
    try:
        return event.subject, str(json.loads(event.body)["event_id"])
    except ValueError, KeyError, TypeError:
        return None


def _holder_bridge(name: str) -> str:
    url = _URL_HOLDER.fullmatch(name)
    return url[1] if url else ""


def _local(sessions: Path, name: str) -> str:
    """The local session id a consumer named for a claude.ai URL holder resolves to; empty for any other name."""
    bridge = _holder_bridge(name)
    return local_id(sessions, f"https://claude.ai/code/{bridge}") if bridge else ""


def running(sessions: Path) -> Callable[[str], bool]:
    """Whether the consumer `name` names, a local session id or a claude.ai URL holder, has a running process."""
    process_of = live_process(sessions)
    return lambda name: process_of(_local(sessions, name) or name) is not None


def route(
    registry: Registry,
    notifier: Notifier,
    sessions: Path,
    quiet: Mapping[str, Collection[str]] | None = None,
    head: Callable[[str, int], str | None] | None = None,
    lane_of: Callable[[str], str | None] | None = None,
    working: Callable[[], str] = lambda: "in_progress",
    closed: Callable[[str], bool] | None = None,
    forgotten: set[str] | None = None,
    frozen: Callable[[str], bool] | None = None,
) -> Route:
    """A session with no registration has no route, so its events stay on its consumer. A consumer named for a
    claude.ai URL holder is the running session whose record in `sessions` carries that bridge id, which registered
    under its local id. `head` is the
    store's head of a repository's pull request by number, empty or None when it holds none. A consumer's event the
    session already received (the server redelivers one whose ack was lost) is acked with no line, the last
    `_SEEN_MAX` of each consumer being remembered. `lane_of` is a task's lane now: a `holder_resume` or
    `review_refused` for a task not In Progress (a restart redelivers a resume whose ack was lost after the task
    parked; a refusal queued behind a busy holder is moot once the repaired task moved to review) is acked with no
    line; `forgotten` is the keys `forget_ended` removed, so a routed registration gone for any other cause is logged once.
    `working` is the lane the board's machine works a task in, `in_progress` unless it names another. `frozen` is
    whether a task is frozen: its session is halted, so its feedback waits unacked (the server redelivers it) until the
    unfreeze resumes the session."""
    seen: dict[str, dict[tuple[str, str], None]] = {}
    routed: dict[str, str] = {}
    gone = forgotten if forgotten is not None else set()

    def registered(name: str) -> tuple[str, Registration | None]:
        if found := registry.get(name):
            return name, found
        local = _local(sessions, name)
        return local, registry.get(local) if local else None

    def find(name: str):
        key, registration = registered(name)
        if registration is None:
            if (last := routed.pop(name, None)) is not None and last not in gone:
                logger.warning("registration %s was routed before and is gone: nothing in this process removed it", last)
            gone.discard(last)
            return None
        routed[name] = key
        gone.discard(key)

        def deliver(events: list[Event]) -> bool:
            own = local_id(sessions, registration.session)
            received = seen.setdefault(name, {})
            sent = [
                event
                for event in events
                if _seen_key(event) not in received
                and not _stale(event)
                and not _unaddressed(event, name)
                and not _closed(event, closed)
                and not _passed(event, head)
                and not _parked(event, lane_of, working)
                and not _quieted(event, quiet or {}, own, sessions)
            ]
            held = [event for event in sent if _held(event, frozen)]
            sent = [event for event in sent if event not in held]
            lines = [line_for(event) for event in sent]
            notified = notifier.notify(registration, lines) if lines else True
            if notified:
                received.update(dict.fromkeys(key for event in sent if (key := _seen_key(event))))
                for key in list(received)[:-_SEEN_MAX]:
                    del received[key]
            delivered = notified and not held
            outcome = (
                "held for the freeze"
                if held
                else "quieted, nothing sent"
                if not lines
                else "delivered"
                if delivered
                else "not delivered"
            )
            logger.info("session %s: %s %s", name, ", ".join(event.subject for event in events), outcome)
            return delivered

        return deliver

    return find


def forget_ended(
    registry: Registry, alive: Callable[[str], str | None], sessions: Path, forgotten: set[str] | None = None
) -> Callable[[Collection[str]], None]:
    """Remove the registration of every session that is neither running nor named by a consumer in `names`: nothing
    is delivered to it, and a session that returns registers again at its next prompt, by the `session_register` hook."""

    def forget(names: Collection[str]) -> None:
        wanted = set(names)
        wanted |= local_ids(sessions, [bridge for name in names if (bridge := _holder_bridge(name))])
        for key in registry.keys():
            if key not in wanted and not ((registration := registry.get(key)) and alive(registration.session)):
                logger.info("registration %s removed: its session is neither named by a consumer nor running", key)
                registry.delete(key)
                if forgotten is not None:
                    forgotten.add(key)

    return forget


def exit_watcher(
    log: EventLog, registry: Registry, sessions: Path, holds: Callable[[str], str | None]
) -> Callable[[], None]:
    """A sync that holds a process descriptor per registered session with a running process: when one exits, a clean
    exit, kill or crash alike, `SESSION_ENDED` lands on the harness machine, under the task `holds` says the session
    holds (the one the actor pinned it to), and names the session so the actor ends its lease."""

    def ended(session: str, pid: int) -> None:
        task = holds(session)
        machine_events.publish(
            "harness",
            "SESSION_ENDED",
            actor="claude-code",
            task=task,
            run=None if task else session,
            event_id=ended_id(session, pid),
            data={"session": session},
            log=log,
        )

    watch = ExitWatch(ended)
    process_of = live_process(sessions)

    def sync() -> None:
        registered = (registration.session for key in registry.keys() if (registration := registry.get(key)))
        watch_registered(registered, process_of, watch.watch)

    return sync
