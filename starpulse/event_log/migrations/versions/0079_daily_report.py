"""Add the daily report: one row per machine, local day and transition, with its count and summed seconds.

The table is empty until moves are recorded; history before this release is the conversion slice's.

Revision ID: 0079
Revises: 0078
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | tuple[str, ...] | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "starpulse_daily_report" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "starpulse_daily_report",
        sa.Column("machine", sa.String(), nullable=False),
        sa.Column("day", sa.String(), nullable=False),
        sa.Column("from_state", sa.String(), nullable=False),
        sa.Column("to_state", sa.String(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seconds", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("machine", "day", "from_state", "to_state", name="pk_starpulse_daily_report"),
    )


def downgrade() -> None:
    raise NotImplementedError("the report is additive, not dropped")
