"""The merge time and merge commit of each stored pull request; null until it merges.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.add_column("starpulse_pull_requests", sa.Column("merged_at", sa.String))
    op.add_column("starpulse_pull_requests", sa.Column("merge_sha", sa.String))


def downgrade() -> None:
    op.drop_column("starpulse_pull_requests", "merge_sha")
    op.drop_column("starpulse_pull_requests", "merged_at")
