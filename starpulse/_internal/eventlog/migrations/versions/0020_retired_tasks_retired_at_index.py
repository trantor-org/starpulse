"""The retired tasks by when they were retired: the board's change poll counts them and reads the latest from the index.

Revision ID: 0020
Revises: 0019
"""

from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    op.create_index("ix_starpulse_retired_tasks_retired_at", "starpulse_retired_tasks", ["retired_at"])


def downgrade() -> None:
    op.drop_index("ix_starpulse_retired_tasks_retired_at", "starpulse_retired_tasks")
