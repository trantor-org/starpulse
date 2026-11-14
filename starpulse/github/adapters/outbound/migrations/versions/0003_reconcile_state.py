"""The reconcile pass's position: a cursor and the last ETag for each thing it reads.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "github_reconcile_state",
        sa.Column("name", sa.String, primary_key=True),
        sa.Column("cursor", sa.String, nullable=False),
        sa.Column("etag", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("github_reconcile_state")
