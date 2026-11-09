"""Lane changes by when they were seen, which the insights read seeks.

The shared metadata does not declare the index; the chain alone makes it.

Revision ID: 0021
Revises: 0020
"""

from alembic import op

revision = "0021"
down_revision = "0020"


def upgrade() -> None:
    op.create_index("ix_starpulse_lane_changes_observed", "starpulse_lane_changes", ["observed_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_starpulse_lane_changes_observed", "starpulse_lane_changes")
