"""Per-day rollups, so a trend outlives the raw events of its day.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "starpulse_day_rollups",
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("team", sa.String, nullable=False),
        sa.Column("machine", sa.String, nullable=False),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("entries", sa.Integer, nullable=False),
        sa.Column("open_entries", sa.Integer, nullable=False),
        sa.Column("seconds", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("day", "team", "machine", "state"),
    )
