"""Drop the cases, lane-interval and lane tables the summaries fold wrote and nothing read.

Revision ID: 0062
Revises: 0061
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0062"
down_revision: str | tuple[str, ...] | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
CONTRACT = True


def upgrade() -> None:
    op.drop_table("starpulse_lanes")
    op.drop_table("starpulse_lane_intervals")
    op.drop_table("starpulse_cases")


def downgrade() -> None:
    raise NotImplementedError("the dropped rows are a fold of the events, not kept")
