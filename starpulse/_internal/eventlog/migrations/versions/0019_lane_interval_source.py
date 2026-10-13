"""Each lane stay's source, kept on the stay itself so the level groups runs without parsing every event id.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"


def upgrade() -> None:
    op.add_column("starpulse_lane_intervals", sa.Column("source", sa.String))
    # a stay's source is the `<source>/` its event id carries, `unattributed` when it carries none
    op.execute(
        "UPDATE starpulse_lane_intervals SET source = "
        "CASE WHEN position('/' in event_id) > 1 THEN split_part(event_id, '/', 1) ELSE 'unattributed' END"
    )


def downgrade() -> None:
    op.drop_column("starpulse_lane_intervals", "source")
