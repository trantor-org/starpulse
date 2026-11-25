"""Give the read model the UUID every board item stores, and the table that resolves a UUID or an alias to its key.

`starpulse_tasks.uuid` is empty for every row until the read model refolds under its new stamp, which fills it from the
Tasks' History; `starpulse_board_keys` is created empty and filled by the same refold. The release before this one neither
reads nor writes either.

Revision ID: 0071
Revises: 0070
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | tuple[str, ...] | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "uuid" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_tasks")}:
        op.add_column("starpulse_tasks", sa.Column("uuid", sa.String(), nullable=False, server_default=""))
    op.create_table(
        "starpulse_board_keys",
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("token"),
        if_not_exists=True,
    )
    op.create_index("ix_starpulse_board_keys_task", "starpulse_board_keys", ["task_id"], if_not_exists=True)


def downgrade() -> None:
    raise NotImplementedError("the column and table are additive, not dropped")
