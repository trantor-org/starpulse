"""The read model's archive is paged newest first: a partial index on the archived Tasks' update time.

Revision ID: 0031
Revises: 0030
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"


def upgrade() -> None:
    op.create_index(
        "ix_starpulse_tasks_archived_updated",
        "starpulse_tasks",
        ["updated_at"],
        sqlite_where=sa.text("archived = 1"),
    )


def downgrade() -> None:
    op.drop_index("ix_starpulse_tasks_archived_updated", "starpulse_tasks")
