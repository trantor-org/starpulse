"""The event store: one append-only stream per subject, appended by compare-and-swap on the stream head."""

from starpulse.event_log.store.event_store import EventStore, NewEvent, StaleVersion, StoredEvent, Upcasters
from starpulse.event_log.store.tables import metadata

__all__ = [
    "metadata",
    "EventStore",
    "NewEvent",
    "StaleVersion",
    "StoredEvent",
    "Upcasters",
]
