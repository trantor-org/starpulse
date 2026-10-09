"""The database event log; the implementation is in `starpulse._internal.eventlog.event_log`."""

from starpulse._internal.eventlog.event_log import (
    Entry,
    EventLog,
    Tail,
)

__all__ = [
    "Entry",
    "EventLog",
    "Tail",
]
