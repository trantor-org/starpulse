"""The findings table of the removed insights API, which nothing reads or writes.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"


def upgrade() -> None:
    # A store stamped from before the chain was built from the declared schema, which no longer has the table.
    op.execute("DROP TABLE IF EXISTS starpulse_insights")


def downgrade() -> None:
    op.create_table(
        "starpulse_insights",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("engine_name", sa.String, nullable=False),
        sa.Column("engine_version", sa.String, nullable=False),
        sa.Column("team", sa.String),
        sa.Column("machine", sa.String),
        sa.Column("state", sa.String),
        sa.Column("task", sa.String),
        sa.Column("severity", sa.String, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("expires_at", sa.Float),
        sa.Column("retracted_at", sa.Float),
    )
    op.create_index("ix_starpulse_insights_live", "starpulse_insights", ["retracted_at", "expires_at"])
