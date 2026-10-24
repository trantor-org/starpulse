"""A task's lane stays by when they began, in place of by when they ended: the level reads them in that order.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    op.create_index("ix_starpulse_lane_intervals_task_entered", "starpulse_lane_intervals", ["task", "entered_at"])
    op.drop_index("ix_starpulse_lane_intervals_task", "starpulse_lane_intervals")


def downgrade() -> None:
    op.create_index("ix_starpulse_lane_intervals_task", "starpulse_lane_intervals", ["task", "left_at"])
    op.drop_index("ix_starpulse_lane_intervals_task_entered", "starpulse_lane_intervals")
