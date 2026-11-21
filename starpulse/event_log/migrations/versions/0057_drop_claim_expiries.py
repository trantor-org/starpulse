"""The claim expiries table, dropped: no sweep has saved a row since the claim TTL went, and nothing reads one.

Revision ID: 0057
Revises: 0056
"""

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
CONTRACT = True


def upgrade() -> None:
    op.drop_table("starpulse_claim_expiries", if_exists=True)


def downgrade() -> None:
    op.create_table(
        "starpulse_claim_expiries",
        sa.Column("task", sa.String, primary_key=True),
        sa.Column("expires_at", sa.Float, nullable=False),
    )
