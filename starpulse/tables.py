"""StarPulse's tables that more than one module reads or writes, in one metadata with the history's own.

The event log (`event_log`) and the history store (`history`) share a database and the `starpulse_gaps` table, so
the tables they share are declared here, where neither module has to import the other.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, Float, Index, Integer, MetaData, String, Table

metadata = MetaData()

#: The append-only event log. `id` is the readers' cursor: SQLite's AUTOINCREMENT never hands a pruned id out again,
#: so a cursor only ever moves forward.
events = Table(
    "starpulse_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stream", String, nullable=False),
    Column("event_id", String, nullable=False, unique=True),
    Column("fields", JSON, nullable=False),
    Column("at", Float, nullable=False),
    Index("ix_starpulse_events_stream", "stream", "id"),
    Index("ix_starpulse_events_at", "at"),
    sqlite_autoincrement=True,
)

#: Entries of a stream (or a span of the event log) that a reader never read before they were trimmed.
gaps = Table(
    "starpulse_gaps",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stream", String, nullable=False),
    Column("after_id", String, nullable=False),
    Column("before_id", String, nullable=False),
    Column("lost", Integer, nullable=False),
    Column("noted_at", Float, nullable=False),
    Index("ux_starpulse_gaps", "stream", "after_id", unique=True),
)
