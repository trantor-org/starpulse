"""Step, case and lane-interval summaries the history store keeps on write.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.create_table(
        "starpulse_step_summaries",
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("machine", sa.String, nullable=False),
        sa.Column("from_state", sa.String, nullable=False),
        sa.Column("to_state", sa.String, nullable=False),
        sa.Column("steps", sa.Integer, nullable=False),
        sa.Column("duration_s", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("day", "machine", "from_state", "to_state"),
    )
    op.create_table(
        "starpulse_cases",
        sa.Column("machine", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("case_id", sa.String, nullable=False),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("since", sa.Float, nullable=False),
        sa.Column("first_at", sa.Float, nullable=False),
        sa.Column("last_event_id", sa.String, nullable=False),
        sa.Column("last_at", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("machine", "source", "kind", "case_id"),
    )
    op.create_table(
        "starpulse_lane_intervals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task", sa.String, nullable=False),
        sa.Column("lane", sa.String, nullable=False),
        sa.Column("entered_at", sa.Float, nullable=False),
        sa.Column("left_at", sa.Float),
        sa.Column("event_id", sa.String, nullable=False, unique=True),
    )
    op.create_index("ix_starpulse_lane_intervals_task", "starpulse_lane_intervals", ["task", "left_at"])
    op.create_index("ix_starpulse_lane_intervals_entered", "starpulse_lane_intervals", ["entered_at"])
    op.create_index("ix_starpulse_lane_intervals_left", "starpulse_lane_intervals", ["left_at"])


def downgrade() -> None:
    op.drop_table("starpulse_lane_intervals")
    op.drop_table("starpulse_cases")
    op.drop_table("starpulse_step_summaries")
