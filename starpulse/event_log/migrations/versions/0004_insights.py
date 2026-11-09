"""The findings an external engine posts through the insights API, kept after a retraction.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
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
