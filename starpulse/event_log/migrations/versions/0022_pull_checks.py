"""When GitHub last answered a read of each repository, which a listing that agrees with the store leaves no record of.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"


def upgrade() -> None:
    op.create_table(
        "starpulse_pull_checks",
        sa.Column("repo", sa.String, primary_key=True),
        sa.Column("checked_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("starpulse_pull_checks")
