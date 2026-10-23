"""The run ledger table, its index and the settings keys, moved from the Autopilot names to the Scheduler's.

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"


def upgrade() -> None:
    # A store stamped from before the chain was built from the declared schema, which already has the new table.
    if not sa.inspect(op.get_bind()).has_table("starpulse_autopilot_runs"):
        return
    op.rename_table("starpulse_autopilot_runs", "starpulse_scheduler_runs")
    op.drop_index("ix_starpulse_autopilot_runs_tier_points", "starpulse_scheduler_runs")
    op.create_index("ix_starpulse_scheduler_runs_tier_points", "starpulse_scheduler_runs", ["tier", "points"])
    op.execute("UPDATE starpulse_settings SET key = 'scheduler.' || substr(key, 11) WHERE key LIKE 'autopilot.%'")


def downgrade() -> None:
    op.execute("UPDATE starpulse_settings SET key = 'autopilot.' || substr(key, 11) WHERE key LIKE 'scheduler.%'")
    op.drop_index("ix_starpulse_scheduler_runs_tier_points", "starpulse_scheduler_runs")
    op.create_index("ix_starpulse_autopilot_runs_tier_points", "starpulse_scheduler_runs", ["tier", "points"])
    op.rename_table("starpulse_scheduler_runs", "starpulse_autopilot_runs")
