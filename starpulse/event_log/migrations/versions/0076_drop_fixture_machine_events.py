"""Delete the machine events timed before 2023, which test fixtures wrote into the live step table.

Revision ID: 0076
Revises: 0075
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | tuple[str, ...] | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EARLIEST_TIME = 1_672_531_200.0  # 2023-01-01


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM starpulse_machine_events WHERE occurred_at < :earliest").bindparams(earliest=_EARLIEST_TIME))


def downgrade() -> None:
    raise NotImplementedError("the deleted rows were fixtures, not history")
