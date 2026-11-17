"""Drop the record of when a Waiting task's Start Criteria were first met: a task waits on an event, not a polled check.

Revision ID: 0051
Revises: 0050
"""

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
#: The reader floor rises: a release older than this still reads and writes the dropped table.
CONTRACT = True


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("starpulse_criteria_met"):  # a store built from the metadata never had it
        op.drop_table("starpulse_criteria_met")


def downgrade() -> None:
    op.create_table(
        "starpulse_criteria_met",
        sa.Column("task", sa.String, primary_key=True),
        sa.Column("met_at", sa.Float, nullable=False),
    )
