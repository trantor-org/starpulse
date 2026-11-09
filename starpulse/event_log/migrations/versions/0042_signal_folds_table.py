"""The analytics views' per-session folds get a table, one row per view and harness session.

Revision ID: 0042
Revises: 0041
"""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("starpulse_signal_folds"):
        op.create_table(
            "starpulse_signal_folds",
            sa.Column("view", sa.String, nullable=False),
            sa.Column("harness", sa.String, nullable=False),
            sa.Column("session", sa.String, nullable=False),
            sa.Column("first_at", sa.Float, nullable=False),
            sa.Column("last_at", sa.Float, nullable=False),
            sa.Column("folded_through", sa.Integer, nullable=False),
            sa.Column("basis", sa.String, nullable=False),
            sa.Column("result", sa.JSON, nullable=False),
            sa.PrimaryKeyConstraint("view", "harness", "session"),
        )
        op.create_index("ix_starpulse_signal_folds_last_at", "starpulse_signal_folds", ["last_at"])
        op.create_index("ix_starpulse_signal_folds_basis", "starpulse_signal_folds", ["basis"])


def downgrade() -> None:
    op.drop_index("ix_starpulse_signal_folds_basis", table_name="starpulse_signal_folds")
    op.drop_index("ix_starpulse_signal_folds_last_at", table_name="starpulse_signal_folds")
    op.drop_table("starpulse_signal_folds")
