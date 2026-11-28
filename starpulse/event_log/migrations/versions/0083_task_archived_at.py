"""Give the read model the time each Task was last archived, so a count of Tasks archived today reads that time.

`updated_at` moves with every Event a Task takes, archived or not, so a write to an archived Task counted it as archived
that day. `archived_at` is set by `Archived` and cleared by `Rehydrated`; this fills it for each archived row from the
`at` of its stream's last `Archived` Event, one seek of the stream's version index per row.

Revision ID: 0083
Revises: 0082
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | tuple[str, ...] | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FILL = """
UPDATE starpulse_tasks SET archived_at = (
    SELECT max(event.at) FROM starpulse_stream_events AS event
    WHERE event.subject_kind = 'task' AND event.subject_id = starpulse_tasks.id AND event.type = 'Archived'
)
WHERE archived = 1
"""


def upgrade() -> None:
    if "archived_at" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_tasks")}:
        op.add_column("starpulse_tasks", sa.Column("archived_at", sa.Float(), nullable=True))
    op.execute(_FILL)
    op.create_index(
        "ix_starpulse_tasks_archived_at",
        "starpulse_tasks",
        ["archived_at"],
        sqlite_where=sa.text("archived = 1"),
        if_not_exists=True,
    )


def downgrade() -> None:
    raise NotImplementedError("the column is additive, not dropped")
