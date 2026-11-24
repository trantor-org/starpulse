"""Drop the answers table.

The release before this one no longer reads or writes the table, which 0063's release classed dead.

Revision ID: 0066
Revises: 0065
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0066"
down_revision: str | tuple[str, ...] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
CONTRACT = True


def upgrade() -> None:
    op.drop_table("starpulse_answers", if_exists=True)


def downgrade() -> None:
    raise NotImplementedError("the dropped rows are a retired cache, not kept")
