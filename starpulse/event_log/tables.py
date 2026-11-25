"""StarPulse's tables that more than one module reads or writes, in one metadata with the history's own.

The event log (`event_log`) and the history store (`history`) share a database, so
the tables they share are declared here, where neither module has to import the other.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    text,
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

#: How far each reader of the log got: an integer position and, for a reader that rebuilds state, the snapshot it
#: rebuilds from. A snapshot the model cannot validate is not read; the reader replays from the log.
checkpoints = Table(
    "starpulse_checkpoints",
    metadata,
    Column("name", String, primary_key=True),
    Column("position", Integer, nullable=False),
    Column("state", JSON(none_as_null=True), nullable=True),
    Column("saved_at", Float, nullable=False),
)

#: An operator setting the instance keeps across restarts: the scheduler switch and the Admin
#: history-window override. One row per key, with the epoch second it was last written; a missing row means the
#: setting's default.
settings = Table(
    "starpulse_settings",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", JSON, nullable=False),
    Column("updated_at", Float, nullable=False),
)

#: What a worker keeps for others to read: its projection, status, beat and metrics, one row per name. `version` rises
#: with each write, so a reader that remembers the version it applied knows when to read again. Operator settings stay
#: in `starpulse_settings`.
worker_state = Table(
    "starpulse_worker_state",
    metadata,
    Column("name", String, primary_key=True),
    Column("state", JSON, nullable=False),
    Column("version", Integer, nullable=False),
    Column("updated_at", Float, nullable=False),
)

#: The one process that holds a singleton worker's role (the sweeper), by role `name`: `holder` is its pid, `taken_at`
#: the epoch second it took the role. A row whose holder process is gone is taken over (`sweeper.lease`).
leases = Table(
    "starpulse_leases",
    metadata,
    Column("name", String, primary_key=True),
    Column("holder", Integer, nullable=False),
    Column("taken_at", Float, nullable=False),
)

#: The scheduler's run ledger: one row per finished run, the labelled data admission learns demand from. `peak` is the
#: demand the run drew per capacity dimension; `recorded_at` is the epoch second the run was recorded (a run imported
#: from the old JSONL file carries that file's modification time). Event-log pruning never touches it.
scheduler_runs = Table(
    "starpulse_scheduler_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task", String, nullable=False),
    Column("tier", String, nullable=False),
    Column("points", Integer, nullable=False),
    Column("outcome", String, nullable=False),
    Column("duration_s", Float, nullable=False),
    Column("peak", JSON, nullable=False),
    Column("recorded_at", Float, nullable=False),
    Index("ix_starpulse_scheduler_runs_tier_points", "tier", "points"),
    sqlite_autoincrement=True,
)

#: The native board's retired tasks: a finished task's file taken off the board, so its reads and numbering scan fewer
#: files, kept whole by its front matter `id` (`task`) under its file `name`, to be restored as that file. `retired_at`
#: is the epoch second it was retired or imported and `milestone` the front matter's, null for a task with none. Event-log
#: pruning never touches it.
retired_tasks = Table(
    "starpulse_retired_tasks",
    metadata,
    Column("task", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("text", Text, nullable=False),
    Column("retired_at", Float, nullable=False),
    Column("milestone", String),
    Index("ix_starpulse_retired_tasks_retired_at", "retired_at"),  # the change poll's count and max read this alone
    Index("ix_starpulse_retired_tasks_milestone", "milestone", "task"),  # a milestone's tasks, by id
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
    Column("title", String),
    Column("rollup", JSON),
    PrimaryKeyConstraint("repo", "number"),
    Index("ix_starpulse_pull_requests_state", "state", "repo"),
)

machine_events = Table(
    "starpulse_machine_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String, nullable=False, unique=True),
    Column("task", String),
    Column("run", String),
    Column("machine", String, nullable=False),
    Column("event", String, nullable=False),
    Column("actor", String),
    Column("occurred_at", Float, nullable=False),
    Column("sha", String),
    Index("ix_starpulse_machine_events_task", "task", "machine", "occurred_at"),
    Index("ix_starpulse_machine_events_run", "run", "machine", "occurred_at"),
)

#: Every qa verdict a lens gave a task, kept per round so a later PASS never hides an earlier CHANGES.
task_verdicts = Table(
    "starpulse_task_verdicts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String, nullable=False, unique=True),
    Column("task", String, nullable=False),
    Column("lens", String, nullable=False),
    Column("round", Integer, nullable=False),
    Column("outcome", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("occurred_at", Float, nullable=False),
    Index("ix_starpulse_task_verdicts_task", "task", "occurred_at"),
)

#: Each pull request a task delivers or cites, keyed by the task's UUID so a renamed task keeps its links. A row is
#: written with its `link-written` event on the `task-link` stream of that UUID, in one transaction.
task_links = Table(
    "starpulse_task_links",
    metadata,
    Column("task", String, nullable=False),
    Column("role", String, nullable=False),
    Column("ref", String, nullable=False),
    Column("requested_by", String, nullable=False),
    Column("at", Float, nullable=False),
    Column("event_id", String, nullable=False),
    PrimaryKeyConstraint("task", "role", "ref"),
    Index("ix_starpulse_task_links_ref", "ref", "role"),
    Index("ux_starpulse_task_links_delivers", "ref", unique=True, sqlite_where=text("role = 'delivers'")),
)

#: One view's fold of one harness session, as plain JSON: the persisted result the analytics views combine, and no
#: signal behind it. A session has a `ledger` row (the state its next export folds from), the `steps`, `cost` and
#: `spend` results, and the skill-cost worker's `counted` row. `folded_through` is the revision of the write that made
#: the row, taken from the `signal_folds_revision` setting. `basis` is dead, written as empty: the baseline squash drops
#: the column. `first_at` and `last_at` are the times of the session's first and last signal.
signal_folds = Table(
    "starpulse_signal_folds",
    metadata,
    Column("view", String, nullable=False),
    Column("harness", String, nullable=False),
    Column("session", String, nullable=False),
    Column("first_at", Float, nullable=False),
    Column("last_at", Float, nullable=False),
    Column("folded_through", Integer, nullable=False),
    Column("basis", String, nullable=False, default=""),
    Column("result", JSON, nullable=False),
    PrimaryKeyConstraint("view", "harness", "session"),
    Index("ix_starpulse_signal_folds_last_at", "last_at"),
    Index("ix_starpulse_signal_folds_basis", "basis"),
)

#: Each session whose `spend` fold names a task (`spend.named`): one task's spend reads its own sessions' folds by it.
#: Derived from `signal_folds` by `views.adapters.outbound.task_spend`.
task_sessions = Table(
    "starpulse_task_sessions",
    metadata,
    Column("task", String, nullable=False),
    Column("harness", String, nullable=False),
    Column("session", String, nullable=False),
    PrimaryKeyConstraint("task", "harness", "session"),
    Index("ix_starpulse_task_sessions_session", "harness", "session"),
)

#: Each task's spend in each phase over every session naming it (`spend.phase_rows`): the peers one task's norms are
#: drawn over, a phase whose last step is in the window standing in with its all-time `wte`. Derived as `task_sessions`.
task_phase_spend = Table(
    "starpulse_task_phase_spend",
    metadata,
    Column("task", String, nullable=False),
    Column("phase", String, nullable=False),
    Column("profile", String, nullable=False),
    Column("wte", Float, nullable=False),
    Column("last_at", Float, nullable=False),
    PrimaryKeyConstraint("task", "phase"),
    Index("ix_starpulse_task_phase_spend_last_at", "last_at"),
)
