"""When each held working task's claim lapses unless renewed, as the claim-TTL sweep's latest pass saw it, so the serving
process can show it without running the sweep.

Revision ID: 0034
Revises: 0033
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"


def upgrade() -> None:
    op.create_table(
        "starpulse_claim_expiries",
        sa.Column("task", sa.String, primary_key=True),
        sa.Column("expires_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("starpulse_claim_expiries")
