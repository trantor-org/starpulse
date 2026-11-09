"""The title of each stored pull request, so a title naming another task can rule it out as this task's delivery.

Null for a record saved before it was kept.

Revision ID: 0045
Revises: 0044
"""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("starpulse_pull_requests")}
    if "title" not in columns:  # a store from before the chain is created whole from the current tables
        op.add_column("starpulse_pull_requests", sa.Column("title", sa.String))


def downgrade() -> None:
    op.drop_column("starpulse_pull_requests", "title")
