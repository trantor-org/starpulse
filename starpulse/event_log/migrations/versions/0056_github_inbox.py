"""The GitHub inbox's tables, which an inbox of its own database kept: the deliveries, each consumer's state on them and
the reconcile pass's cursors. `starpulse migrate` carries an old inbox file's rows in once.

Revision ID: 0056
Revises: 0055
"""

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"


def upgrade() -> None:
    # SQLite DDL is non-transactional: a rerun after a failed upgrade finds the tables made so far.
    if not sa.inspect(op.get_bind()).has_table("github_inbox"):
        op.create_table(
            "github_inbox",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("delivery_id", sa.String, nullable=False, unique=True),
            sa.Column("source", sa.String, nullable=False),
            sa.Column("event", sa.String, nullable=False),
            sa.Column("action", sa.String, nullable=False),
            sa.Column("repository", sa.String, nullable=False),
            sa.Column("body", sa.LargeBinary, nullable=False),
            sa.Column("received_at", sa.Float, nullable=False),
        )
        op.create_index("github_inbox_fact", "github_inbox", ["repository", "event", "action", "received_at"])
    if not sa.inspect(op.get_bind()).has_table("github_inbox_state"):
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
    if not sa.inspect(op.get_bind()).has_table("github_reconcile_state"):
        op.create_table(
            "github_reconcile_state",
            sa.Column("name", sa.String, primary_key=True),
            sa.Column("cursor", sa.String, nullable=False),
            sa.Column("etag", sa.String, nullable=True),
        )


def downgrade() -> None:
    op.drop_table("github_reconcile_state")
    op.drop_table("github_inbox_state")
    op.drop_table("github_inbox")
