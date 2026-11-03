"""A lease table: the one process that holds a singleton worker's role, by name.

Revision ID: 0044
Revises: 0043
"""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("starpulse_leases"):
        op.create_table(
            "starpulse_leases",
            sa.Column("name", sa.String, primary_key=True),
            sa.Column("holder", sa.Integer, nullable=False),
            sa.Column("taken_at", sa.Float, nullable=False),
        )


def downgrade() -> None:
    op.drop_table("starpulse_leases")
