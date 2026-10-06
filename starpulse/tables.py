"""StarPulse's tables that more than one module reads or writes, in one metadata with the history's own.

The event log (`event_log`) and the history store (`history`) share a database and the `starpulse_gaps` table, so
the tables they share are declared here, where neither module has to import the other.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, Date, Float, Index, Integer, MetaData, PrimaryKeyConstraint, String, Table

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

#: The Board a reader saved, with the cursor of the last entry it reflects, so a restart resumes after it.
board_state = Table(
    "starpulse_board_state",
    metadata,
    Column("stream", String, primary_key=True),
    Column("after_id", String, nullable=False),
    Column("state", JSON, nullable=False),
    Column("saved_at", Float, nullable=False),
)

#: What a hub keeps of a day after its raw events are dropped (`hub.enforce_retention`): per team, machine and state,
#: how many tasks or runs entered the state that UTC day (`entries`), how many of those had not left it when the day was
#: rolled up (`open_entries`), and the seconds the others stayed. A hub writes it; an IC instance never does.
day_rollups = Table(
    "starpulse_day_rollups",
    metadata,
    Column("day", Date, nullable=False),
    Column("team", String, nullable=False),
    Column("machine", String, nullable=False),
    Column("state", String, nullable=False),
    Column("entries", Integer, nullable=False),
    Column("open_entries", Integer, nullable=False),
    Column("seconds", Float, nullable=False),
    PrimaryKeyConstraint("day", "team", "machine", "state"),
)
