"""When each Waiting task's Start Criteria were first seen all met, so a restart keeps how long a task has been workable.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "starpulse_criteria_met",
        sa.Column("task", sa.String, primary_key=True),
        sa.Column("met_at", sa.Float, nullable=False),
    )
