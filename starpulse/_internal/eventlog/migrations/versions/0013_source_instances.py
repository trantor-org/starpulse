"""The instance each forwarding source is bound to, and the id an instance's forwarder sends a hub.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.create_table(
        "starpulse_source_instances",
        sa.Column("source", sa.String, primary_key=True),
        sa.Column("instance", sa.String, nullable=False),
        sa.Column("bound_at", sa.Float, nullable=False),
    )
    op.create_table(
        "starpulse_forward_instances",
        sa.Column("name", sa.String, primary_key=True),
        sa.Column("instance", sa.String, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("starpulse_forward_instances")
    op.drop_table("starpulse_source_instances")
