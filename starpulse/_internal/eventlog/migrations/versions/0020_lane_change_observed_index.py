"""SQLite's lane changes by when they were seen, which the insights read seeks; the hub reads them on Postgres.

The index is SQLite's alone: the hub's Postgres store answers the same read from `ix_starpulse_lane_changes_task` and
its partitioned events, and the shared metadata does not declare it.

Revision ID: 0020
Revises: 0019
"""

from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.create_index("ix_starpulse_lane_changes_observed", "starpulse_lane_changes", ["observed_at", "id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index("ix_starpulse_lane_changes_observed", "starpulse_lane_changes")
