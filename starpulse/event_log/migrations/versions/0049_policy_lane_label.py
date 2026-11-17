"""The status a task file spells for each policy lane: `In Progress` for the `in_progress` lane.

Revision ID: 0049
Revises: 0048
"""

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_policy_lanes")}
    if "label" not in columns:  # a store from before the chain is created whole from the current tables
        op.add_column("starpulse_policy_lanes", sa.Column("label", sa.String))


def downgrade() -> None:
    op.drop_column("starpulse_policy_lanes", "label")
