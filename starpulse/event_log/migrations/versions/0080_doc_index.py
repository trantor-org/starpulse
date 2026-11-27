"""Store an index of the board's docs: id, title, type and path.

The table is created empty: the board fills it from the doc files it finds when it opens, and the release before this one
neither reads nor writes it.

Revision ID: 0080
Revises: 0079
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: str | tuple[str, ...] | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "starpulse_doc_index",
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("path"),
        if_not_exists=True,
    )
    op.create_index("ix_starpulse_doc_index_id", "starpulse_doc_index", ["id"], if_not_exists=True)


def downgrade() -> None:
    raise NotImplementedError("the table is additive, not dropped")
