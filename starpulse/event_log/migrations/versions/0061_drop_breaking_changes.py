"""Drop the breaking-change log: a break is a `postmortem` doc now.

Revision ID: 0061
Revises: 0060
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061"
down_revision: str | tuple[str, ...] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
CONTRACT = True


def upgrade() -> None:
    op.drop_table("starpulse_breaking_change_detections")
    op.drop_table("starpulse_breaking_changes")


def downgrade() -> None:
    raise NotImplementedError("the dropped breaking-change rows are not kept")
