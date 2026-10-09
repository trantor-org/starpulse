"""The pull requests the PR store read from GitHub, one row per repository and number.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.create_table(
        "starpulse_pull_requests",
        sa.Column("repo", sa.String, nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("is_draft", sa.Boolean, nullable=False),
        sa.Column("mergeable", sa.String, nullable=False),
        sa.Column("base", sa.String, nullable=False),
        sa.Column("head", sa.String, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("checks", sa.String, nullable=False),
        sa.Column("required", sa.JSON, nullable=False),
        sa.Column("threads", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.String, nullable=False),
        sa.Column("fetched_at", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("repo", "number"),
    )
    op.create_index("ix_starpulse_pull_requests_state", "starpulse_pull_requests", ["state", "repo"])


def downgrade() -> None:
    op.drop_index("ix_starpulse_pull_requests_state", "starpulse_pull_requests")
    op.drop_table("starpulse_pull_requests")
