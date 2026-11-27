"""Store each case's Trace and cluster key.

The table is created empty: the session ledger writes a row when a case ends, and the release before this one neither
reads nor writes it. Cases that ended before this change have no row until the one-time conversion writes them.

Revision ID: 0081
Revises: 0080
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0081"
down_revision: str | tuple[str, ...] | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "starpulse_traces",
        sa.Column("harness", sa.String(), nullable=False),
        sa.Column("session", sa.String(), nullable=False),
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("skill", sa.String(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("ended_at", sa.Float(), nullable=False),
        sa.Column("activities", sa.JSON(), nullable=False),
        sa.Column("cluster_key", sa.String(), nullable=False),
        sa.Column("unfinished", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("harness", "session", "task", "skill", "started_at"),
        if_not_exists=True,
    )
    op.create_index("ix_starpulse_traces_cluster_key", "starpulse_traces", ["cluster_key"], if_not_exists=True)


def downgrade() -> None:
    raise NotImplementedError("the table is additive, not dropped")
