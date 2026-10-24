"""The event store: one append-only table of stream Events and the outbox that delivers them.

`starpulse_stream_events` keeps one row per Event under a unique (subject kind, subject id, version), which backs the
compare-and-swap on a stream head. Nothing prunes or rewrites it. `starpulse_outbox` has a row per Event, written in the
append's transaction and marked sent once the stream acknowledges it.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"


def upgrade() -> None:
    op.create_table(
        "starpulse_stream_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String, nullable=False, unique=True),
        sa.Column("subject_kind", sa.String, nullable=False),
        sa.Column("subject_id", sa.String, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("at", sa.Float, nullable=False),
        sa.Column("actor", sa.String, nullable=False),
        sa.Column("writer", sa.String, nullable=False),
        sa.Column("definition_hash", sa.String, nullable=True),
        sa.Column("causation_id", sa.String, nullable=True),
        sa.Column("correlation_id", sa.String, nullable=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.UniqueConstraint("subject_kind", "subject_id", "version", name="uq_starpulse_stream_events_version"),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "starpulse_outbox",
        sa.Column("event_id", sa.String, sa.ForeignKey("starpulse_stream_events.event_id"), primary_key=True),
        sa.Column("sent_at", sa.Float, nullable=True),
    )
    op.create_index("ix_starpulse_outbox_unsent", "starpulse_outbox", ["sent_at"])


def downgrade() -> None:
    op.drop_table("starpulse_outbox")
    op.drop_table("starpulse_stream_events")
