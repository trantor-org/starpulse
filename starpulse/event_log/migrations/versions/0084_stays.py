"""Store each Stay of a task: the state it held on a machine, when it began, its length and its spend per model and effort.

The table is created empty: the recorder opens a row when a task enters a state and closes it with its length when the
task leaves, and the session ledger adds each Model step to the rows of its task that hold its time. States left before
this change have no row until the one-time conversion writes them.

Revision ID: 0084
Revises: 0083
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | tuple[str, ...] | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "starpulse_stays",
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("task_uuid", sa.String(), nullable=True),
        sa.Column("machine", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("entered_at", sa.Float(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=True),
        sa.Column("reconstructed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("spend", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("task", "machine", "entered_at"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_starpulse_stays_task_uuid", "starpulse_stays", ["task_uuid", "machine", "entered_at"], if_not_exists=True
    )


def downgrade() -> None:
    raise NotImplementedError("the table is additive, not dropped")
