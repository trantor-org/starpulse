"""Give each table that names a task by key a `task_uuid` beside it.

The column is null for every existing row. The writers fill it from `starpulse_board_keys` as they insert, and the read
model's fold of a task fills the rows of that task that lack it, so the refold the new stamp triggers is the backfill. The
release before this one neither reads nor writes the column. The two partial indexes serve the fold's lookup of a task's
unnamed rows in the tables whose indexes do not lead with the key.

Revision ID: 0073
Revises: 0072
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | tuple[str, ...] | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "starpulse_machine_events",
    "starpulse_machine_tasks",
    "starpulse_lane_changes",
    "starpulse_task_verdicts",
    "starpulse_scheduler_runs",
    "starpulse_task_criteria",
)
_UNNAMED = {"starpulse_machine_tasks": "ix_starpulse_machine_tasks_unnamed", "starpulse_scheduler_runs": "ix_starpulse_scheduler_runs_unnamed"}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in _TABLES:
        if "task_uuid" not in {column["name"] for column in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("task_uuid", sa.String(), nullable=True))
    for table, index in _UNNAMED.items():
        op.create_index(index, table, ["task"], if_not_exists=True, sqlite_where=sa.text("task_uuid IS NULL"))


def downgrade() -> None:
    raise NotImplementedError("the columns are additive, not dropped")
