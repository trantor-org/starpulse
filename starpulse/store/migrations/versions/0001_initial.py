"""The history schema as the first hub release created it: the event log, history and board-state tables.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "starpulse_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("stream", sa.String, nullable=False),
        sa.Column("event_id", sa.String, nullable=False),
        sa.Column("fields", sa.JSON, nullable=False),
        sa.Column("at", sa.Float, nullable=False),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_starpulse_events_stream", "starpulse_events", ["stream", "id"])
    op.create_index("ix_starpulse_events_at", "starpulse_events", ["at"])
    op.create_table(
        "starpulse_gaps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("stream", sa.String, nullable=False),
        sa.Column("after_id", sa.String, nullable=False),
        sa.Column("before_id", sa.String, nullable=False),
        sa.Column("lost", sa.Integer, nullable=False),
        sa.Column("noted_at", sa.Float, nullable=False),
    )
    op.create_index("ux_starpulse_gaps", "starpulse_gaps", ["stream", "after_id"], unique=True)
    op.create_table(
        "starpulse_board_state",
        sa.Column("stream", sa.String, primary_key=True),
        sa.Column("after_id", sa.String, nullable=False),
        sa.Column("state", sa.JSON, nullable=False),
        sa.Column("saved_at", sa.Float, nullable=False),
    )
    op.create_table(
        "starpulse_machine_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String, nullable=False),
        sa.Column("task", sa.String),
        sa.Column("run", sa.String),
        sa.Column("machine", sa.String, nullable=False),
        sa.Column("event", sa.String, nullable=False),
        sa.Column("actor", sa.String),
        sa.Column("occurred_at", sa.Float, nullable=False),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_starpulse_machine_events_task", "starpulse_machine_events", ["task", "machine", "occurred_at"])
    op.create_table(
        "starpulse_lane_changes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String, nullable=False),
        sa.Column("task", sa.String, nullable=False),
        sa.Column("old_status", sa.String),
        sa.Column("new_status", sa.String, nullable=False),
        sa.Column("observed_at", sa.Float, nullable=False),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_starpulse_lane_changes_task", "starpulse_lane_changes", ["task", "observed_at"])
    op.create_table(
        "starpulse_learned_steps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workflow", sa.String, nullable=False),
        sa.Column("step", sa.String, nullable=False),
        sa.Column("depends", sa.Text, nullable=False),
    )
    op.create_index("ux_starpulse_learned_steps", "starpulse_learned_steps", ["workflow", "step"], unique=True)
    op.create_table(
        "starpulse_cursors",
        sa.Column("stream", sa.String, primary_key=True),
        sa.Column("after_id", sa.Integer, nullable=False),
    )
