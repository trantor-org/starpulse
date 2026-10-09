"""Each lane's stays by when they ended, with when they began, in place of the lane index: the health read seeks it.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.create_index("ix_starpulse_lane_intervals_stay", "starpulse_lane_intervals", ["lane", "left_at", "entered_at"])
    op.drop_index("ix_starpulse_lane_intervals_lane", "starpulse_lane_intervals")


def downgrade() -> None:
    op.create_index("ix_starpulse_lane_intervals_lane", "starpulse_lane_intervals", ["lane", "left_at"])
    op.drop_index("ix_starpulse_lane_intervals_stay", "starpulse_lane_intervals")
