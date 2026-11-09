"""The native board's retired tasks, kept in the history store rather than as files the board scans.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    op.create_table(
        "starpulse_retired_tasks",
        sa.Column("task", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("retired_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("starpulse_retired_tasks")
