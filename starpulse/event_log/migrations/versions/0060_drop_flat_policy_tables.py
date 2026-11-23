"""Drop the flat `starpulse_policy_*` tables: the active policy version is the source, and a release that reads them stops at the previous revision.

Revision ID: 0060
Revises: 0059
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0060"
down_revision: str | tuple[str, ...] | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
CONTRACT = True

_FLAT = ("lanes", "routes", "exits", "watches", "rules", "vocabularies", "profiles", "tools")


def upgrade() -> None:
    for name in _FLAT:
        op.drop_table(f"starpulse_policy_{name}", if_exists=True)


def downgrade() -> None:
    raise NotImplementedError("a policy version cannot be flattened back into the tables it replaced")
