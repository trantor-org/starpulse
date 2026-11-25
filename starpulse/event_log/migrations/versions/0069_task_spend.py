"""Add the task_spend family's tables, so one task's spend reads its own sessions' folds and its peers' phase totals.

They are created empty and unstamped: `views.adapters.outbound.task_spend` fills them from the spend folds as it
follows them. The release before this one neither reads nor writes them.

Revision ID: 0069
Revises: 0068
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: str | tuple[str, ...] | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "starpulse_task_sessions",
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("harness", sa.String(), nullable=False),
        sa.Column("session", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("task", "harness", "session"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_starpulse_task_sessions_session", "starpulse_task_sessions", ["harness", "session"], if_not_exists=True
    )
    op.create_table(
        "starpulse_task_phase_spend",
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("wte", sa.Float(), nullable=False),
        sa.Column("last_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("task", "phase"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_starpulse_task_phase_spend_last_at", "starpulse_task_phase_spend", ["last_at"], if_not_exists=True
    )


def downgrade() -> None:
    op.drop_table("starpulse_task_phase_spend")
    op.drop_table("starpulse_task_sessions")
