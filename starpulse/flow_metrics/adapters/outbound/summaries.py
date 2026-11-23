"""The step summaries table, which nothing writes or reads, kept declared until a migration drops it."""

from sqlalchemy import Column, Date, Float, Integer, PrimaryKeyConstraint, String, Table

from starpulse.event_log.tables import metadata

step_summaries = Table(
    "starpulse_step_summaries",
    metadata,
    Column("day", Date, nullable=False),
    Column("machine", String, nullable=False),
    Column("from_state", String, nullable=False),
    Column("to_state", String, nullable=False),
    Column("steps", Integer, nullable=False),
    Column("duration_s", Float, nullable=False),
    PrimaryKeyConstraint("day", "machine", "from_state", "to_state"),
)
