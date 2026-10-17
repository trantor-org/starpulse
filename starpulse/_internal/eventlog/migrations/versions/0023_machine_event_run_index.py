"""A run-keyed machine event by its run, which `/api/history` reads when `?task=` names a run id.

Revision ID: 0023
Revises: 0022
"""

from alembic import op

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    op.create_index(
        "ix_starpulse_machine_events_run", "starpulse_machine_events", ["run", "machine", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_starpulse_machine_events_run", "starpulse_machine_events")
