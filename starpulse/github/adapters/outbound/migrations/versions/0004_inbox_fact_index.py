"""An index the reconcile pass reads to find the webhook rows that already reported a fact.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.create_index("github_inbox_fact", "github_inbox", ["repository", "event", "action", "received_at"])


def downgrade() -> None:
    op.drop_index("github_inbox_fact", "github_inbox")
