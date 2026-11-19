"""An index on the machine tasks' `active_at`, so the windowed machine read searches it rather than scanning the table.

Revision ID: 0054
Revises: 0053
"""

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"

INDEX = "ix_starpulse_machine_tasks_active"


def upgrade() -> None:
    if INDEX not in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("starpulse_machine_tasks")}:
        op.create_index(INDEX, "starpulse_machine_tasks", ["active_at"])


def downgrade() -> None:
    op.drop_index(INDEX, "starpulse_machine_tasks")
