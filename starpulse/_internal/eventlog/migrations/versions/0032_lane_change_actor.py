"""Who made each lane change: the actor a board write named, null for a change only observed.

Revision ID: 0030
Revises: 0029
"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_lane_changes")}
    if "actor" not in columns:  # a store from before the chain is created whole from the current tables
        op.add_column("starpulse_lane_changes", sa.Column("actor", sa.String))


def downgrade() -> None:
    op.drop_column("starpulse_lane_changes", "actor")
