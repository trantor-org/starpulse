"""Each lifecycle machine's tasks as rows, one per (machine, task), which the Board child's projector folds from `machine:events`.

Revision ID: 0039
Revises: 0038
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("starpulse_machine_tasks"):  # a store built from the metadata has it
        return
    op.create_table(
        "starpulse_machine_tasks",
        sa.Column("machine", sa.String, primary_key=True),
        sa.Column("task", sa.String, primary_key=True),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("agent", sa.JSON, nullable=False),
        sa.Column("active_at", sa.Float, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
    )
    op.create_index("ix_starpulse_machine_tasks_machine_active", "starpulse_machine_tasks", ["machine", "active_at"])
    op.create_index("ix_starpulse_machine_tasks_seq", "starpulse_machine_tasks", ["seq"])


def downgrade() -> None:
    op.drop_table("starpulse_machine_tasks")
