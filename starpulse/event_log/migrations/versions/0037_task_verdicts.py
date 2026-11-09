"""The qa verdicts a lens gave a task, one row per verdict, which `/api/events` and the history read.

Revision ID: 0037
Revises: 0036
"""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("starpulse_task_verdicts"):  # a store built from the metadata has it
        return
    op.create_table(
        "starpulse_task_verdicts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String, nullable=False, unique=True),
        sa.Column("task", sa.String, nullable=False),
        sa.Column("lens", sa.String, nullable=False),
        sa.Column("round", sa.Integer, nullable=False),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("reason", sa.String, nullable=False),
        sa.Column("occurred_at", sa.Float, nullable=False),
    )
    op.create_index("ix_starpulse_task_verdicts_task", "starpulse_task_verdicts", ["task", "occurred_at"])


def downgrade() -> None:
    op.drop_table("starpulse_task_verdicts")
