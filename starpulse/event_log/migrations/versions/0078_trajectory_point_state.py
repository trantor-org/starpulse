"""Keep the state a task entered and the machine version it happened under on each Trajectory point.

`starpulse_machine_events.state` and `.machine_version` are written as the event is recorded, and
`starpulse_lane_changes.machine_version` beside the lane the change entered (`new_status`). All are null for a row
recorded before this release; the conversion slice fills them. The release before this one neither reads nor writes them.

Revision ID: 0078
Revises: 0077
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | tuple[str, ...] | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = {
    "starpulse_machine_events": ("state", "machine_version"),
    "starpulse_lane_changes": ("machine_version",),
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, names in _COLUMNS.items():
        held = {column["name"] for column in inspector.get_columns(table)}
        for name in names:
            if name not in held:
                op.add_column(table, sa.Column(name, sa.String()))


def downgrade() -> None:
    raise NotImplementedError("the columns are additive, not dropped")
