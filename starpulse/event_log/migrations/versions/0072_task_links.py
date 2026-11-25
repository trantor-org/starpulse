"""Store each pull request a task delivers or cites, keyed by the task's UUID.

The table is created empty: only a holder's link request writes a row, with its `link-written` event, and the release
before this one neither reads nor writes it.

Revision ID: 0072
Revises: 0071
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: str | tuple[str, ...] | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "starpulse_task_links",
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("at", sa.Float(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("task", "role", "ref"),
        if_not_exists=True,
    )
    op.create_index("ix_starpulse_task_links_ref", "starpulse_task_links", ["ref", "role"], if_not_exists=True)
    op.create_index(
        "ux_starpulse_task_links_delivers",
        "starpulse_task_links",
        ["ref"],
        unique=True,
        sqlite_where=sa.text("role = 'delivers'"),
        if_not_exists=True,
    )


def downgrade() -> None:
    raise NotImplementedError("the table is additive, not dropped")
