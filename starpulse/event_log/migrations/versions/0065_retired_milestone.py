"""Index a retired task's milestone, so a milestone read touches only that milestone's rows.

The column holds the front matter's `milestone`, null for a task with none; each existing row is filled from its text.
The release before this one ignores the column and still keeps rows without it, which this one reads by id only.

Revision ID: 0065
Revises: 0064
"""

from collections.abc import Sequence

import sqlalchemy as sa
import yaml
from alembic import op

revision: str = "0065"
down_revision: str | tuple[str, ...] | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "starpulse_retired_tasks"
_INDEX = "ix_starpulse_retired_tasks_milestone"


def _milestone(text: str) -> str | None:
    text = text.replace("\r\n", "\n")
    end = text.find("\n---", 4)
    if not text.startswith("---\n") or end == -1:
        return None
    try:
        front = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return str(front.get("milestone") or "").strip() or None if isinstance(front, dict) else None


def upgrade() -> None:
    bind = op.get_bind()
    if "milestone" not in {column["name"] for column in sa.inspect(bind).get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column("milestone", sa.String()))
    table = sa.table(_TABLE, sa.column("task", sa.String), sa.column("text", sa.Text), sa.column("milestone", sa.String))
    found = [
        {"key": row.task, "milestone": milestone}
        for row in bind.execute(sa.select(table.c.task, table.c.text))
        if (milestone := _milestone(row.text))
    ]
    if found:
        bind.execute(
            table.update().where(table.c.task == sa.bindparam("key")).values(milestone=sa.bindparam("milestone")), found
        )
    op.create_index(_INDEX, _TABLE, ["milestone", "task"], if_not_exists=True)


def downgrade() -> None:
    raise NotImplementedError("the index and column are additive, not dropped")
