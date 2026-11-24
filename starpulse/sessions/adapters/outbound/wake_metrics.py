"""`starpulse_wakes_delivered_total{event,lane}` and `starpulse_wake_repeats_total{event,lane}`: the event lines a session received.

The notifier reports each line it posted. A line counts by its event and the lane of its task now, a `moved` line by the lane
it moved to, since the board's read side lags a move by a moment (`none` for a subject
no task names, `unknown` when the board's read side is not up yet). A repeat is a line whose subject and payload
(its text without the event id) this session already received. Session and task ids are in the log line, never a label.
The bridge runs in the `contexts` child and the Page API serves `/metrics`, so the counters travel as the exposition
kept in the event log's state, as `starpulse.bridge.metrics` does; a restart resets them.
"""

import hashlib
import logging
import re
from collections.abc import Callable, Sequence

from prometheus_client import CollectorRegistry, Counter, generate_latest

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_text
from starpulse.sessions.ports.notify import Line

logger = logging.getLogger(__name__)

STATE = "bridge.wakes"
_MOVED_TO = re.compile(r"\blane=(\S+)")
#: Deliveries remembered for repeat detection, oldest forgotten first.
_REMEMBERED = 4096


def _parts(subject: str) -> tuple[str, str]:
    """The task a `starpulse.<board>.task.<task>.<event>` subject names, else empty, and its event."""
    parts = subject.split(".")
    return (parts[3] if parts[2:3] == ["task"] and len(parts) > 3 else ""), parts[4] if len(parts) > 4 else "unknown"


class Wakes:
    def __init__(self, log: EventLog, lane_of: Callable[[str], str | None]) -> None:
        """`lane_of` is a task's lane now, None for a task the board holds no open row for, `unknown` is its own to say."""
        self._log, self._lane_of = log, lane_of
        self._registry = CollectorRegistry()
        labels = ["event", "lane"]
        self._delivered = Counter(
            "starpulse_wakes_delivered", "Event lines posted to agent sessions", labels, registry=self._registry
        )
        self._repeats = Counter(
            "starpulse_wake_repeats", "Lines whose subject and payload the session already received", labels, registry=self._registry
        )
        self._seen: dict[tuple[str, str, str], None] = {}

    def __call__(self, session: str, lines: Sequence[Line]) -> None:
        if not lines:
            return
        try:
            for line in lines:
                self._record(session, line)
            self._log.put_state(STATE, generate_latest(self._registry).decode())
        except Exception:
            logger.warning("session %s: the wakes were not counted", session, exc_info=True)

    def _record(self, session: str, line: Line) -> None:
        task, event = _parts(line.subject)
        moved = _MOVED_TO.search(line.payload) if event == "moved" else None
        lane = moved[1] if moved else (self._lane_of(task) or "closed") if task else "none"
        digest = hashlib.sha256((line.payload or line.text).encode()).hexdigest()[:12]
        key = (session, line.subject, digest)
        repeat = key in self._seen
        self._seen.pop(key, None)
        self._seen[key] = None
        if len(self._seen) > _REMEMBERED:
            del self._seen[next(iter(self._seen))]
        self._delivered.labels(event, lane).inc()
        if repeat:
            self._repeats.labels(event, lane).inc()
        logger.info(
            "wake delivered: session=%s task=%s subject=%s payload=%s lane=%s repeat=%s",
            session, task or "-", line.subject, digest, lane, repeat,
        )  # fmt: skip


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The wakes' metrics text as last kept; empty before one was delivered or when the log cannot be read."""
    return kept_text(log, STATE)
