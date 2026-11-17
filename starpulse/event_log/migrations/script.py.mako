<%!
    # Renders the literal ruff format keeps as is, so a generated revision
    # (the alembic-heads DAG commits one unedited) passes the lint gate.
    def literal(value):
        if isinstance(value, (tuple, list)):
            return "(\n" + "".join(f'    "{item}",\n' for item in value) + ")"
        return "None" if value is None else f'"{value}"'
%>\
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

from collections.abc import Sequence
% if upgrades:

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}\
% endif

revision: str = ${literal(up_revision)}
down_revision: str | tuple[str, ...] | None = ${literal(down_revision)}
branch_labels: str | Sequence[str] | None = ${literal(branch_labels)}
depends_on: str | Sequence[str] | None = ${literal(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
