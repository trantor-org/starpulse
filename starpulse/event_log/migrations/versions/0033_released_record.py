"""The claim-TTL release a Task's claim ended in, as a nullable JSON column on the read model's task rows.

Revision ID: 0033
Revises: 0032
"""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_tasks")}
    if "released" not in columns:  # a store from before the chain is created whole from the current tables
        op.add_column("starpulse_tasks", sa.Column("released", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("starpulse_tasks", "released")
