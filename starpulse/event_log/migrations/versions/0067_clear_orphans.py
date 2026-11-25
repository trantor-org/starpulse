"""Delete the rows whose foreign key points at nothing.

Every connection now runs with `PRAGMA foreign_keys=ON`, which refuses a write that leaves such a row; the rows the
earlier, unenforced writes left are read by nothing (a criterion of a deleted task, an active hash with no version).

Revision ID: 0067
Revises: 0066
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0067"
down_revision: str | tuple[str, ...] | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORPHANS = (
    ("starpulse_task_criteria", "task_id", "starpulse_tasks", "id"),
    ("starpulse_machine_active", "hash", "starpulse_machine_versions", "hash"),
    ("starpulse_policy_active", "hash", "starpulse_policy_versions", "hash"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for child, column, parent, key in _ORPHANS:
        bind.exec_driver_sql(f"DELETE FROM {child} WHERE {column} NOT IN (SELECT {key} FROM {parent})")


def downgrade() -> None:
    raise NotImplementedError("the deleted rows pointed at nothing")
