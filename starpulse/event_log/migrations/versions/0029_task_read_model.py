"""The Task read model: one row per Task and one per Acceptance Criterion or Definition of Done item.

`starpulse_tasks` holds StarPulse's own fields as typed columns and a deployment's declared fields in `fields`; the
generated column and index for each queried declared field are added at projector start from the `[board]` declaration,
not here. The indexes on state, milestone and assignee cover unarchived rows only, so an archive of any size costs the
live board nothing. `seq` is the stream position of the last Event folded in, which is the cursor of a delta read.

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"


def upgrade() -> None:
    op.create_table(
        "starpulse_tasks",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("updated_at", sa.Float, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("priority", sa.String, nullable=False),
        sa.Column("milestone", sa.String, nullable=False),
        sa.Column("assignee", sa.String, nullable=False),
        sa.Column("archived", sa.Boolean, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("plan", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("final_summary", sa.Text, nullable=False),
        sa.Column("labels", sa.JSON, nullable=False),
        sa.Column("dependencies", sa.JSON, nullable=False),
        sa.Column("references", sa.JSON, nullable=False),
        sa.Column("documentation", sa.JSON, nullable=False),
        sa.Column("modified_files", sa.JSON, nullable=False),
        sa.Column("comments", sa.JSON, nullable=False),
        sa.Column("fields", sa.JSON, nullable=False),
        sa.Column("meta", sa.JSON, nullable=False),
    )
    op.create_index("ix_starpulse_tasks_seq", "starpulse_tasks", ["seq"])
    for column in ("id", "milestone", "assignee"):
        op.create_index(
            f"ix_starpulse_tasks_live_{column}", "starpulse_tasks", [column], sqlite_where=sa.text("archived = 0")
        )
    op.create_index(
        "ix_starpulse_tasks_live_state", "starpulse_tasks", ["state", "id"], sqlite_where=sa.text("archived = 0")
    )
    op.create_table(
        "starpulse_task_criteria",
        sa.Column("task_id", sa.String, sa.ForeignKey("starpulse_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String, primary_key=True),
        sa.Column("n", sa.Integer, primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("checked", sa.Boolean, nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("starpulse_task_criteria")
    op.drop_table("starpulse_tasks")
