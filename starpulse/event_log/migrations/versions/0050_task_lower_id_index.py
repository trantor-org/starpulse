"""A Task by its id in any case, which `ReadModel.task` falls back to for an id it does not hold as spelled.

Revision ID: 0050
Revises: 0049
"""

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"


def upgrade() -> None:
    op.create_index("ix_starpulse_tasks_lower_id", "starpulse_tasks", [sa.text("lower(id)")], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_starpulse_tasks_lower_id", "starpulse_tasks")
