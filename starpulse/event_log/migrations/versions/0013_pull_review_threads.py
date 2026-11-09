"""The head branch and the unresolved review threads (id and first-comment author) of each stored pull request.

Both are null for a record saved before they were kept, so a reader falls back to GitHub for it rather than reading it
as a pull request with no threads.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.add_column("starpulse_pull_requests", sa.Column("head_ref", sa.String))
    op.add_column("starpulse_pull_requests", sa.Column("unresolved", sa.JSON))


def downgrade() -> None:
    op.drop_column("starpulse_pull_requests", "unresolved")
    op.drop_column("starpulse_pull_requests", "head_ref")
