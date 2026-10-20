"""The tasks in each lane now and when each lane was first entered, per source, kept on write beside the lane intervals.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.create_table(
        "starpulse_lanes",
        sa.Column("source", sa.String, nullable=False),
        sa.Column("lane", sa.String, nullable=False),
        sa.Column("open_tasks", sa.Integer, nullable=False),
        sa.Column("first_at", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("source", "lane"),
    )
    op.create_index("ix_starpulse_lane_intervals_lane", "starpulse_lane_intervals", ["lane", "left_at"])
    op.create_index("ix_starpulse_cases_state", "starpulse_cases", ["machine", "state"])


def downgrade() -> None:
    op.drop_index("ix_starpulse_cases_state", "starpulse_cases")
    op.drop_index("ix_starpulse_lane_intervals_lane", "starpulse_lane_intervals")
    op.drop_table("starpulse_lanes")
