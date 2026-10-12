"""StarPulse's tables that more than one module reads or writes, in one metadata with the history's own.

The event log (`event_log`) and the history store (`history`) share a database and the `starpulse_gaps` table, so
the tables they share are declared here, where neither module has to import the other.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    Float,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
)

metadata = MetaData()

#: Where the database records the revision it is at, named so it never meets a host project's own Alembic table.
VERSION_TABLE = "starpulse_alembic_version"

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

#: The one instance each forwarding source's token speaks for: the first instance id that source's forwarder sent.
#: A hub writes it, on the first batch a source sends and never again until an operator drops the row to rebind.
source_instances = Table(
    "starpulse_source_instances",
    metadata,
    Column("source", String, primary_key=True),
    Column("instance", String, nullable=False),
    Column("bound_at", Float, nullable=False),
)

#: An operator setting the instance keeps across restarts: the autopilot switch, the forwarder opt-in and the Admin
#: history-window override. One row per key, with the epoch second it was last written; a missing row means the
#: setting's default.
settings = Table(
    "starpulse_settings",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", JSON, nullable=False),
    Column("updated_at", Float, nullable=False),
)

#: The autopilot's run ledger: one row per finished run, the labelled data admission learns demand from. `peak` is the
#: demand the run drew per capacity dimension; `recorded_at` is the epoch second the run was recorded (a run imported
#: from the old JSONL file carries that file's modification time). Event-log pruning never touches it.
autopilot_runs = Table(
    "starpulse_autopilot_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task", String, nullable=False),
    Column("tier", String, nullable=False),
    Column("points", Integer, nullable=False),
    Column("outcome", String, nullable=False),
    Column("duration_s", Float, nullable=False),
    Column("peak", JSON, nullable=False),
    Column("recorded_at", Float, nullable=False),
    Index("ix_starpulse_autopilot_runs_tier_points", "tier", "points"),
    sqlite_autoincrement=True,
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

#: The findings an engine posted through the insights API: one row per `id`, replaced by a re-post, and kept after a
#: retraction (`retracted_at`) so the history shows what the engine said. An engine reads this table directly, so its
#: columns are versioned with the package. A finding is live while `retracted_at` is null and `expires_at` is null or
#: later than now.
insights = Table(
    "starpulse_insights",
    metadata,
    Column("id", String, primary_key=True),
    Column("engine_name", String, nullable=False),
    Column("engine_version", String, nullable=False),
    Column("team", String),
    Column("machine", String),
    Column("state", String),
    Column("task", String),
    Column("severity", String, nullable=False),
    Column("text", Text, nullable=False),
    Column("evidence", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float),
    Column("retracted_at", Float),
    Index("ix_starpulse_insights_live", "retracted_at", "expires_at"),
)

#: Each pull request the PR store read from GitHub, one row per (repository, number), replaced by each read of an open
#: one and never read again once `state` is MERGED or CLOSED (a MERGED row without `merge_sha` is read until it has one). `checks` is the required-check rollup (pass, failing,
#: pending, none), `required` each required check as {name, result}, `updated_at` GitHub's own ISO 8601 UTC text
#: (equal-width, so it sorts as time), `fetched_at` the epoch second this row was read and `detail` what the Board's
#: per-task pull request state reads beside the served fields (merge commit and time, commits behind main, changed
#: files and the CI history), null in a row saved before it was kept.
pull_requests = Table(
    "starpulse_pull_requests",
    metadata,
    Column("repo", String, nullable=False),
    Column("number", Integer, nullable=False),
    Column("state", String, nullable=False),
    Column("is_draft", Boolean, nullable=False),
    Column("mergeable", String, nullable=False),
    Column("base", String, nullable=False),
    Column("head", String, nullable=False),
    Column("body", Text, nullable=False),
    Column("checks", String, nullable=False),
    Column("required", JSON, nullable=False),
    Column("threads", Integer, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("merged_at", String),
    Column("merge_sha", String),
    Column("fetched_at", Float, nullable=False),
    Column("detail", JSON, nullable=True),
    Column("head_ref", String),
    Column("unresolved", JSON),
    PrimaryKeyConstraint("repo", "number"),
    Index("ix_starpulse_pull_requests_state", "state", "repo"),
)
