"""The harness-telemetry signals get a table of their own, one row per signal key.

Revision ID: 0039
Revises: 0038
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("starpulse_signals"):
        op.create_table(
            "starpulse_signals",
            sa.Column("key", sa.String, primary_key=True),
            sa.Column("harness", sa.String, nullable=False),
            sa.Column("session", sa.String, nullable=False),
            sa.Column("time", sa.Float, nullable=False),
            sa.Column("kind", sa.String, nullable=False),
            sa.Column("fields", sa.JSON, nullable=False),
        )
        op.create_index("ix_starpulse_signals_time", "starpulse_signals", ["time"])
        op.create_index("ix_starpulse_signals_session", "starpulse_signals", ["harness", "session", "time"])


def downgrade() -> None:
    op.drop_index("ix_starpulse_signals_session", table_name="starpulse_signals")
    op.drop_index("ix_starpulse_signals_time", table_name="starpulse_signals")
    op.drop_table("starpulse_signals")
