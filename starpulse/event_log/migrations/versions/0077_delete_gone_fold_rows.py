"""Delete the fold rows of the views the code no longer lists.

The release before the signals revision (0063) kept writing `health`, `runs`, `cases` and `trace_cases` rows until it was
replaced, so 24 of them came back after 0063 had deleted them. Nothing writes or reads those views now.

Revision ID: 0077
Revises: 0076
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: str | tuple[str, ...] | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GONE = ("health", "runs", "cases", "trace_cases")


def upgrade() -> None:
    folds = sa.table("starpulse_signal_folds", sa.column("view"))
    op.get_bind().execute(sa.delete(folds).where(folds.c.view.in_(_GONE)))


def downgrade() -> None:
    raise NotImplementedError("the deleted rows are a fold of signals no table keeps")
