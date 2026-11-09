"""The fingerprint of the machines the history summaries were folded under, so an edited machine rebuilds them.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.create_table("starpulse_summary_basis", sa.Column("fingerprint", sa.String, primary_key=True))


def downgrade() -> None:
    op.drop_table("starpulse_summary_basis")
