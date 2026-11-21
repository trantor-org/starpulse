"""The gzip of each stored snapshot body, made by the Board writer so a read serves bytes it never compresses.

Revision ID: 0055
Revises: 0054
"""

import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_snapshots")}
    if "gzipped" not in columns:  # a store built from the metadata has it
        op.add_column("starpulse_snapshots", sa.Column("gzipped", sa.LargeBinary, nullable=True))


def downgrade() -> None:
    op.drop_column("starpulse_snapshots", "gzipped")
