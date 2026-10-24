"""What the Board's per-task pull request state reads beside a stored pull request's served fields.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.add_column("starpulse_pull_requests", sa.Column("detail", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("starpulse_pull_requests", "detail")
