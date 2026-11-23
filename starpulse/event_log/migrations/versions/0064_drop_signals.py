"""Drop the signals table and the checkpoints' unread `schema_version` column.

The release before this one no longer reads the table, which 0063 classed dead; no reader reads the column.

Revision ID: 0064
Revises: 0063
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | tuple[str, ...] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
CONTRACT = True


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("starpulse_signals"):
        op.drop_table("starpulse_signals")
    if "schema_version" in {column["name"] for column in inspector.get_columns("starpulse_checkpoints")}:
        with op.batch_alter_table("starpulse_checkpoints") as batch:
            batch.drop_column("schema_version")


def downgrade() -> None:
    raise NotImplementedError("the dropped rows are stale signals, not kept")
