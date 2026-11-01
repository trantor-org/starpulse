"""Rebuild the machine tasks' rows: the fold that wrote them was not idempotent, so a stream read twice doubled a trail's steps.

Clearing the rows and their checkpoint makes the next fold (the Board child's, or `starpulse migrate`) read `machine:events`
from the start and place each entry once.

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM starpulse_machine_tasks"))
    op.execute(sa.text("DELETE FROM starpulse_checkpoints WHERE name = 'read-model:machine-tasks'"))


def downgrade() -> None:
    """Nothing to undo: the cleared rows are rebuilt by the next fold either way."""
