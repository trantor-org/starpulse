"""The telemetry analytics' answers move from a checkpoint snapshot to one row per view and query, and the checkpoints
no longer read, saved or replayed (`analytics-answers`, the board's projections and the native and replica cursors) are
deleted.

Revision ID: 0038
Revises: 0037
"""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"

#: The checkpoints the chain drops: the analytics snapshot, the board projections, the native-board cursors and the
#: board replica's saved state. A replay rebuilds any of them from the log.
_STALE = ("analytics-answers", "backlog:projection%", "native:%", "board:replica@%")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("starpulse_answers"):
        op.create_table(
            "starpulse_answers",
            sa.Column("view", sa.String, primary_key=True),
            sa.Column("query", sa.String, primary_key=True),
            sa.Column("body", sa.LargeBinary, nullable=False),
            sa.Column("status", sa.Integer, nullable=False),
            sa.Column("folded_at", sa.Float, nullable=False),
        )
        op.create_index("ix_starpulse_answers_folded_at", "starpulse_answers", ["folded_at"])
    checkpoints = sa.table("starpulse_checkpoints", sa.column("name", sa.String))
    for pattern in _STALE:
        op.execute(checkpoints.delete().where(checkpoints.c.name.like(pattern)))


def downgrade() -> None:
    op.drop_index("ix_starpulse_answers_folded_at", table_name="starpulse_answers")
    op.drop_table("starpulse_answers")
