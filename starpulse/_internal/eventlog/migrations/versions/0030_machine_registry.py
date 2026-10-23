"""The machine registry: every compiled definition by its hash, and the one active per machine.

Revision ID: 0030
Revises: 0029
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"


def upgrade() -> None:
    op.create_table(
        "starpulse_machine_versions",
        sa.Column("hash", sa.String, primary_key=True),
        sa.Column("machine", sa.String, nullable=False),
        sa.Column("document", sa.JSON, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_table(
        "starpulse_machine_active",
        sa.Column("machine", sa.String, primary_key=True),
        sa.Column("hash", sa.String, sa.ForeignKey("starpulse_machine_versions.hash"), nullable=False),
        sa.Column("activated_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("starpulse_machine_active")
    op.drop_table("starpulse_machine_versions")
