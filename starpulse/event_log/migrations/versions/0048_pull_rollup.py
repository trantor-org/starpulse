"""The head rollup of each stored pull request: `{sha, state}` of the last `pr-checks` rollup event.

Null for a record no rollup event has reached; the board reads such a record as checks not all passed.

Revision ID: 0048
Revises: 0047
"""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_pull_requests")}
    if "rollup" not in columns:  # a store from before the chain is created whole from the current tables
        op.add_column("starpulse_pull_requests", sa.Column("rollup", sa.JSON))


def downgrade() -> None:
    op.drop_column("starpulse_pull_requests", "rollup")
