"""The operator settings an instance keeps across restarts, moved from files beside the config into the history store.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    op.create_table(
        "starpulse_settings",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("starpulse_settings")
