"""The read marks of the retired pull request listing reconcile, which the event-fed store has no use for.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    op.drop_table("starpulse_pull_checks")


def downgrade() -> None:
    op.create_table(
        "starpulse_pull_checks",
        sa.Column("repo", sa.String, primary_key=True),
        sa.Column("checked_at", sa.Float, nullable=False),
    )
