"""Keep the build a machine event named, so a wait on a commit reads an event recorded before it parked.

The column holds the event's `data.sha`, null for an event that named none and for every row recorded before this
release. The release before this one neither reads nor writes it.

Revision ID: 0070
Revises: 0069
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | tuple[str, ...] | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "starpulse_machine_events"


def upgrade() -> None:
    if "sha" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column("sha", sa.String()))


def downgrade() -> None:
    raise NotImplementedError("the column is additive, not dropped")
