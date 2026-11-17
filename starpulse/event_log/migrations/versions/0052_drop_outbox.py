"""The event store's outbox, dropped: nothing read, marked or deleted a row, so it grew one row per Event.

Revision ID: 0052
Revises: 0051
"""

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
CONTRACT = True


def upgrade() -> None:
    op.drop_table("starpulse_outbox", if_exists=True)


def downgrade() -> None:
    op.create_table(
        "starpulse_outbox",
        sa.Column("event_id", sa.String, sa.ForeignKey("starpulse_stream_events.event_id"), primary_key=True),
        sa.Column("sent_at", sa.Float),
    )
    op.create_index("ix_starpulse_outbox_unsent", "starpulse_outbox", ["sent_at"])
