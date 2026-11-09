"""The autopilot's run ledger, moved from a JSONL file beside the config into the history store.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    op.create_table(
        "starpulse_autopilot_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task", sa.String, nullable=False),
        sa.Column("tier", sa.String, nullable=False),
        sa.Column("points", sa.Integer, nullable=False),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("duration_s", sa.Float, nullable=False),
        sa.Column("peak", sa.JSON, nullable=False),
        sa.Column("recorded_at", sa.Float, nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_starpulse_autopilot_runs_tier_points", "starpulse_autopilot_runs", ["tier", "points"])


def downgrade() -> None:
    op.drop_table("starpulse_autopilot_runs")
