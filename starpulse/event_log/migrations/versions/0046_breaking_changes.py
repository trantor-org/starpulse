"""The commits that broke the default branch and what each detector saw of them, fed by `breaking-change:events`.

Revision ID: 0046
Revises: 0045
"""

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("starpulse_breaking_changes"):  # a store built from the metadata has it
        op.create_table(
            "starpulse_breaking_changes",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("commit_sha", sa.String, nullable=False, unique=True),
            sa.Column("pr", sa.Integer),
            sa.Column("task", sa.String),
            sa.Column("outcome", sa.String),
            sa.Column("first_seen", sa.Float, nullable=False),
            sa.Column("postmortem_task", sa.String),
        )
    if not inspector.has_table("starpulse_breaking_change_detections"):
        op.create_table(
            "starpulse_breaking_change_detections",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.String, nullable=False, unique=True),
            sa.Column("commit_sha", sa.String, nullable=False),
            sa.Column("detector", sa.String, nullable=False),
            sa.Column("outcome", sa.String),
            sa.Column("evidence", sa.String),
            sa.Column("occurred_at", sa.Float, nullable=False),
            sa.UniqueConstraint("commit_sha", "detector"),
        )


def downgrade() -> None:
    op.drop_table("starpulse_breaking_change_detections")
    op.drop_table("starpulse_breaking_changes")
