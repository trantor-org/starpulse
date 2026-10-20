"""The shelved hub's partitioning of raw events by day, kept in the chain as a no-op.

The store is SQLite, which has no partitions: its events stay the table 0001 made. The revision stays so a store that
recorded it still finds it in the chain.

Revision ID: 0002
Revises: 0001
"""

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    pass
