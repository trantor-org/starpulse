"""The inbox of GitHub deliveries: one immutable row per `delivery_id`, holding the raw body.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "github_inbox",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("delivery_id", sa.String, nullable=False, unique=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("event", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("repository", sa.String, nullable=False),
        sa.Column("body", sa.LargeBinary, nullable=False),
        sa.Column("received_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("github_inbox")
