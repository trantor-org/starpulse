"""The board's policy as tables: lanes, routes, exits, watches, rules, vocabularies, profiles and the tools a lane allows.

Revision ID: 0047
Revises: 0046
"""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"

_TABLES = (
    "starpulse_policy_lanes",
    "starpulse_policy_routes",
    "starpulse_policy_exits",
    "starpulse_policy_watches",
    "starpulse_policy_rules",
    "starpulse_policy_vocabularies",
    "starpulse_policy_profiles",
    "starpulse_policy_tools",
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLES[0]):  # a store built from the metadata has them all
        return
    op.create_table(
        "starpulse_policy_lanes",
        sa.Column("name", sa.String, primary_key=True),
        sa.Column("role", sa.String),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("skill", sa.String),
    )
    op.create_table(
        "starpulse_policy_routes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("target", sa.String, nullable=False),
        sa.Column("condition", sa.JSON),
    )
    op.create_table(
        "starpulse_policy_exits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event", sa.String, nullable=False),
        sa.Column("actor", sa.String, nullable=False),
        sa.Column("trigger", sa.String, nullable=False),
    )
    op.create_table(
        "starpulse_policy_watches",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("lane", sa.String, nullable=False),
        sa.Column("fact", sa.String, nullable=False),
        sa.Column("event", sa.String, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
    )
    op.create_table(
        "starpulse_policy_rules",
        sa.Column("position", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("on", sa.JSON, nullable=False),
        sa.Column("require", sa.JSON, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("skill", sa.String, nullable=False),
        sa.Column("unless_actor", sa.JSON, nullable=False),
    )
    op.create_table(
        "starpulse_policy_vocabularies",
        sa.Column("name", sa.String, nullable=False),
        sa.Column("value", sa.String, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("name", "value"),
    )
    op.create_table(
        "starpulse_policy_profiles",
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("profile", sa.String, nullable=False),
        sa.PrimaryKeyConstraint("kind", "size"),
    )
    op.create_table(
        "starpulse_policy_tools",
        sa.Column("lane", sa.String, nullable=False),
        sa.Column("tool", sa.String, nullable=False),
        sa.PrimaryKeyConstraint("lane", "tool"),
    )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
