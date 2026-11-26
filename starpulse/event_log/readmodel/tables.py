"""The Task read model's tables. Only this package imports them (the `readmodel-table-private` import contract), so
every row is written by the projector and read through `ReadModel`."""

from sqlalchemy import JSON, Boolean, Column, Float, ForeignKey, Index, Integer, LargeBinary, MetaData, String, Table, Text, text

metadata = MetaData()

#: One row per Task: StarPulse's own fields as typed columns, a deployment's declared fields in `fields`, anything else
#: in `meta`. `seq` is the position of the last Event folded in, which is the cursor a delta read resumes from.
tasks = Table(
    "starpulse_tasks",
    metadata,
    Column("id", String, primary_key=True),
    Column("seq", Integer, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("title", Text, nullable=False),
    Column("type", String, nullable=False),
    Column("state", String, nullable=False),
    Column("priority", String, nullable=False),
    Column("milestone", String, nullable=False),
    Column("assignee", String, nullable=False),
    Column("released", JSON, nullable=True),
    Column("archived", Boolean, nullable=False),
    Column("description", Text, nullable=False),
    Column("plan", Text, nullable=False),
    Column("notes", Text, nullable=False),
    Column("final_summary", Text, nullable=False),
    Column("labels", JSON, nullable=False),
    Column("dependencies", JSON, nullable=False),
    Column("references", JSON, nullable=False),
    Column("documentation", JSON, nullable=False),
    Column("modified_files", JSON, nullable=False),
    Column("comments", JSON, nullable=False),
    Column("fields", JSON, nullable=False),
    Column("meta", JSON, nullable=False),
    #: The item's stored UUID, copied from its `meta`: `board_keys` is what resolves one.
    Column("uuid", String, nullable=False, server_default=""),
    Index("ix_starpulse_tasks_seq", "seq"),
    Index("ix_starpulse_tasks_lower_id", text("lower(id)")),
    Index("ix_starpulse_tasks_live_id", "id", sqlite_where=text("archived = 0")),
    Index("ix_starpulse_tasks_live_state", "state", "id", sqlite_where=text("archived = 0")),
    Index("ix_starpulse_tasks_live_milestone", "milestone", sqlite_where=text("archived = 0")),
    Index("ix_starpulse_tasks_live_assignee", "assignee", sqlite_where=text("archived = 0")),
    Index("ix_starpulse_tasks_archived_updated", "updated_at", sqlite_where=text("archived = 1")),
    Index("ix_starpulse_tasks_live_set", "archived", "state", "updated_at", sqlite_where=text("archived = 0")),
)

#: One row per name besides its key that a Task answers to: its stored UUID (`kind` uuid) and each alias it lists.
board_keys = Table(
    "starpulse_board_keys",
    metadata,
    Column("token", String, primary_key=True),
    Column("task_id", String, nullable=False),
    Column("kind", String, nullable=False),
    Index("ix_starpulse_board_keys_task", "task_id"),
)

#: One row per (machine, task): the state the task holds on that lifecycle machine, the drawn agent as JSON and when the
#: machine last placed it. `seq` is the `machine:events` position folded in, the cursor `/api/events` resumes from.
machine_tasks = Table(
    "starpulse_machine_tasks",
    metadata,
    Column("machine", String, primary_key=True),
    Column("task", String, primary_key=True),
    Column("state", String, nullable=False),
    Column("agent", JSON, nullable=False),
    Column("active_at", Float, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("task_uuid", String),
    Index("ix_starpulse_machine_tasks_machine_active", "machine", "active_at"),
    Index("ix_starpulse_machine_tasks_seq", "seq"),
    Index("ix_starpulse_machine_tasks_active", "active_at"),
    Index("ix_starpulse_machine_tasks_unnamed", "task", sqlite_where=text("task_uuid IS NULL")),
    Index("ix_starpulse_machine_tasks_task_uuid", "task_uuid"),
)

#: One row per Acceptance Criterion or Definition of Done item, numbered from 1 within its kind.
criteria = Table(
    "starpulse_task_criteria",
    metadata,
    Column("task_id", String, ForeignKey("starpulse_tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("kind", String, primary_key=True),
    Column("n", Integer, primary_key=True),
    Column("text", Text, nullable=False),
    Column("checked", Boolean, nullable=False),
    Column("evidence", Text, nullable=False),
    Column("task_uuid", String),
    Index("ix_starpulse_task_criteria_task_uuid", "task_uuid"),
)

#: The Board writer's encoded snapshot, one row (view `live`): `seq` is the last `starpulse_snapshot_deltas`
#: row the body reflects.
snapshots = Table(
    "starpulse_snapshots",
    metadata,
    Column("view", String, primary_key=True),
    Column("seq", Integer, nullable=False),
    Column("body", LargeBinary, nullable=False),
    #: The body's gzip, None for a body too small to be worth compressing.
    Column("gzipped", LargeBinary),
    Column("stored_at", Float, nullable=False),
)

#: Each change the Board writer's feed published, numbered in the order it was folded; the rows behind the retained
#: window are pruned, so a cursor older than the first row reads a fresh snapshot.
snapshot_deltas = Table(
    "starpulse_snapshot_deltas",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=False),
    Column("kind", String, nullable=False),
    Column("data", JSON, nullable=False),
)

#: The two read-model table families, each stamped and swapped alone.
TASK_TABLES = (tasks, criteria, board_keys)
MACHINE_TABLES = (machine_tasks,)
SNAPSHOT_TABLES = (snapshots, snapshot_deltas)
