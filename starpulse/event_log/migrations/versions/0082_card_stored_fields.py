"""Keep a card's phase, substate, skill, pull requests and open-dependency count on its `starpulse_tasks` row.

The projector restates them when they change, so a list reads them with no resolver pass. A row folded before this
release holds none until its next change or a replay. The release before this one neither reads nor writes them.

Revision ID: 0082
Revises: 0081
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0082"
down_revision: str | tuple[str, ...] | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    sa.Column("phase", sa.String()),
    sa.Column("substate", sa.String()),
    sa.Column("skill", sa.String()),
    sa.Column("prs", sa.JSON(), nullable=False, server_default="[]"),
    sa.Column("open_dependencies", sa.Integer(), nullable=False, server_default="0"),
)


def upgrade() -> None:
    held = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_tasks")}
    for column in _COLUMNS:
        if column.name not in held:
            op.add_column("starpulse_tasks", column)


def downgrade() -> None:
    raise NotImplementedError("the columns are additive, not dropped")
