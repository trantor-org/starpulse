"""One checkpoint table for the reader cursors and the saved Boards.

A cursor becomes a checkpoint with no state; a saved Board keeps its state and takes the integer before the `-` of its
`after_id` as the position. Both land at schema version 0, which no reader's snapshot model has, so the first start
rebuilds each Board from the log. No release reads both tables, so the old ones are dropped here.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"

_cursors = sa.table("starpulse_cursors", sa.column("stream", sa.String), sa.column("after_id", sa.Integer))
_boards = sa.table(
    "starpulse_board_state",
    sa.column("stream", sa.String),
    sa.column("after_id", sa.String),
    sa.column("state", sa.JSON),
    sa.column("saved_at", sa.Float),
)


def upgrade() -> None:
    checkpoints = op.create_table(
        "starpulse_checkpoints",
        sa.Column("name", sa.String, primary_key=True),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("state", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("saved_at", sa.Float, nullable=False),
    )
    db = op.get_bind()
    rows = [
        {"name": stream, "position": after_id, "schema_version": 0, "state": None, "saved_at": 0.0}
        for stream, after_id in db.execute(sa.select(_cursors.c.stream, _cursors.c.after_id))
    ]
    for stream, after_id, state, saved_at in db.execute(sa.select(*_boards.c)):
        rows.append(
            {
                "name": stream,
                "position": int(after_id.partition("-")[0]),
                "schema_version": 0,
                "state": state,
                "saved_at": saved_at,
            }
        )
    if rows:
        op.bulk_insert(checkpoints, rows)
    op.drop_table("starpulse_cursors")
    op.drop_table("starpulse_board_state")


def downgrade() -> None:
    op.create_table(
        "starpulse_board_state",
        sa.Column("stream", sa.String, primary_key=True),
        sa.Column("after_id", sa.String, nullable=False),
        sa.Column("state", sa.JSON, nullable=False),
        sa.Column("saved_at", sa.Float, nullable=False),
    )
    op.create_table(
        "starpulse_cursors",
        sa.Column("stream", sa.String, primary_key=True),
        sa.Column("after_id", sa.Integer, nullable=False),
    )
    op.drop_table("starpulse_checkpoints")
