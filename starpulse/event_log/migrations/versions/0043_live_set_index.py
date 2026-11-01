"""The partial index that serves the live Task set (`queries.live`): unarchived Tasks by state and last change.

Revision ID: 0043
Revises: 0042
"""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"

INDEX = "ix_starpulse_tasks_live_set"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("starpulse_tasks"):  # a store built from the metadata has the index already
        return
    if INDEX in {index["name"] for index in inspector.get_indexes("starpulse_tasks")}:
        return
    op.create_index(INDEX, "starpulse_tasks", ["archived", "state", "updated_at"], sqlite_where=sa.text("archived = 0"))


def downgrade() -> None:
    op.drop_index(INDEX, table_name="starpulse_tasks")
