"""The state of each delivery for each consumer: pending, done, skipped or dead, with its attempts and next attempt.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "github_inbox_state",
        sa.Column("delivery_id", sa.String, nullable=False),
        sa.Column("consumer", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("next_attempt_at", sa.Float, nullable=False),
        sa.Column("last_error", sa.String, nullable=True),
        sa.Column("updated_at", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("delivery_id", "consumer"),
    )
    op.create_index("ix_github_inbox_state_due", "github_inbox_state", ["consumer", "status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_github_inbox_state_due", table_name="github_inbox_state")
    op.drop_table("github_inbox_state")
