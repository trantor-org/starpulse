"""What a worker keeps for others to read moves from the operator settings into its own table, each name with a version
that rises on every write, so a reader polls the version and no worker appends an empty event to ring a doorbell.

Revision ID: 0036
Revises: 0035
"""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"

#: The settings keys, and key prefixes, that are worker state rather than an operator's choice.
_KEYS = (
    "runs.projection",
    "pulls.projection",
    "pulls.metrics",
    "pulls.poller",
    "scheduler.status",
    "scheduler.inflight",
    "scheduler.starts",
    "scheduler.sample",
    "scheduler.held",
    "scheduler.harness_pauses",
    "scheduler.decisions",
)
_PREFIXES = ("runs.beat.", "cursor-context:")


def _kept() -> str:
    prefixes = " OR ".join(f"key LIKE '{prefix}%'" for prefix in _PREFIXES)
    keys = ", ".join(f"'{key}'" for key in _KEYS)
    return f"key IN ({keys}) OR {prefixes}"


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("starpulse_worker_state"):
        op.create_table(
            "starpulse_worker_state",
            sa.Column("name", sa.String, primary_key=True),
            sa.Column("state", sa.JSON, nullable=False),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("updated_at", sa.Float, nullable=False),
        )
    op.execute(
        "INSERT INTO starpulse_worker_state (name, state, version, updated_at) "
        f"SELECT key, value, 1, updated_at FROM starpulse_settings WHERE {_kept()}"
    )
    op.execute(f"DELETE FROM starpulse_settings WHERE {_kept()}")


def downgrade() -> None:
    op.execute(
        "INSERT INTO starpulse_settings (key, value, updated_at) "
        "SELECT name, state, updated_at FROM starpulse_worker_state"
    )
    op.drop_table("starpulse_worker_state")
