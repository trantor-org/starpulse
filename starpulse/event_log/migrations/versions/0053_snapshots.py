"""The Board writer's stored snapshot and the deltas it published since, which the API serves.

Revision ID: 0053
Revises: 0052
"""

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"


def upgrade() -> None:
    have = sa.inspect(op.get_bind()).has_table
    if not have("starpulse_snapshots"):  # a store built from the metadata has them
        op.create_table(
            "starpulse_snapshots",
            sa.Column("view", sa.String, primary_key=True),
            sa.Column("seq", sa.Integer, nullable=False),
            sa.Column("body", sa.LargeBinary, nullable=False),
            sa.Column("stored_at", sa.Float, nullable=False),
        )
    if not have("starpulse_snapshot_deltas"):
        op.create_table(
            "starpulse_snapshot_deltas",
            sa.Column("seq", sa.Integer, primary_key=True, autoincrement=False),
            sa.Column("kind", sa.String, nullable=False),
            sa.Column("data", sa.JSON, nullable=False),
        )


def downgrade() -> None:
    op.drop_table("starpulse_snapshot_deltas")
    op.drop_table("starpulse_snapshots")
