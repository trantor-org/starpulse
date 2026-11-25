"""The event store's tables. Only this package imports them (the `store-table-private` import contract), so every
write to a stream goes through `EventStore`."""

from sqlalchemy import JSON, Column, Float, ForeignKey, Integer, MetaData, String, Table, UniqueConstraint

metadata = MetaData()

#: One row per Event, in the order appended. Nothing prunes or rewrites it.
stream_events = Table(
    "starpulse_stream_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String, nullable=False, unique=True),
    Column("subject_kind", String, nullable=False),
    Column("subject_id", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("type", String, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("at", Float, nullable=False),
    Column("actor", String, nullable=False),
    Column("writer", String, nullable=False),
    Column("definition_hash", String),
    Column("causation_id", String),
    Column("correlation_id", String),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("subject_kind", "subject_id", "version", name="uq_starpulse_stream_events_version"),
    sqlite_autoincrement=True,
)

#: Every compiled definition ever activated, kept by the hash of the whole compiled definition so an Event is read
#: under the version that wrote it. Nothing prunes or rewrites it.
machine_versions = Table(
    "starpulse_machine_versions",
    metadata,
    Column("hash", String, primary_key=True),
    Column("machine", String, nullable=False),
    Column("document", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
)

#: The version a machine's commands validate against: one row per machine.
machine_active = Table(
    "starpulse_machine_active",
    metadata,
    Column("machine", String, primary_key=True),
    Column("hash", String, ForeignKey("starpulse_machine_versions.hash"), nullable=False),
    Column("activated_at", Float, nullable=False),
)

#: The newest Task Event id, as a statement for `EventLog.run_on_wake`'s `signal`.
NEWEST_EVENT = f"SELECT max(id) FROM {stream_events.name}"
