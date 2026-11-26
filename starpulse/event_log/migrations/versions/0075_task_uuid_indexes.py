"""Index `task_uuid` in the five tables a reader asks by a task's UUID.

The readers of a task's lane changes, machine events, scheduler runs, machine rows and criteria resolve its key to its UUID
and filter on `task_uuid`; without an index each such read scans the table. The key indexes stay for the writers that
still ask by key. The verdicts table has no reader.

Revision ID: 0075
Revises: 0074
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0075"
down_revision: str | tuple[str, ...] | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = {
    "ix_starpulse_machine_events_task_uuid": ("starpulse_machine_events", ["task_uuid", "machine", "occurred_at"]),
    "ix_starpulse_lane_changes_task_uuid": ("starpulse_lane_changes", ["task_uuid", "observed_at"]),
    "ix_starpulse_scheduler_runs_task_uuid": ("starpulse_scheduler_runs", ["task_uuid"]),
    "ix_starpulse_machine_tasks_task_uuid": ("starpulse_machine_tasks", ["task_uuid"]),
    "ix_starpulse_task_criteria_task_uuid": ("starpulse_task_criteria", ["task_uuid"]),
}


def upgrade() -> None:
    for name, (table, columns) in _INDEXES.items():
        op.create_index(name, table, columns, if_not_exists=True)


def downgrade() -> None:
    raise NotImplementedError("the indexes are additive, not dropped")
