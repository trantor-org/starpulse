"""The shelved hub's per-day rollups, kept in the chain as a no-op.

A SQLite store never holds them. The revision stays so a store that recorded it still finds it in the chain.

Revision ID: 0003
Revises: 0002
"""

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    pass
