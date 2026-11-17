"""The changes to what lets the autopilot admit: one event on the existing log per change of the switch, a session cap,
the quiet hours or a usage-limit pause, holding the old and new value, so the hours it could not admit read from them."""

from typing import Any

from starpulse.event_log.event_log import EventLog

STREAM = "scheduler.changes"


def record(log: EventLog, kind: str, old: Any, new: Any, **extra: Any) -> None:
    """Append one `kind` event with `old` and `new` unless they are equal; a log that cannot be written drops it."""
    if old != new:
        log.publish(STREAM, {"kind": kind, **extra, "old": old, "new": new})
