"""Policy as versions plus one active row, like machines.

Revision ID: 0059
Revises: 0058

The flat `starpulse_policy_*` tables the chain wrote become the first version, kept by the hash of its document and made active;
a store whose tables hold no rows gets no version and is still governed by its files. The next revision drops the flat tables.
"""

import json
import time
from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | tuple[str, ...] | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Each flat table, its columns (a JSON one is marked) and the columns its rows were read in order of: the document `rows` gives.
_FLAT: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "lanes": (("name", "role", "position", "skill", "label"), (), ("position",)),
    "routes": (("event", "source", "target", "condition"), ("condition",), ("id",)),
    "exits": (("event", "actor", "trigger"), (), ("id",)),
    "watches": (("lane", "fact", "event", "position"), (), ("lane", "position")),
    "rules": (("position", "on", "require", "reason", "skill", "unless_actor"), ("on", "require", "unless_actor"), ("position",)),
    "vocabularies": (("name", "value", "position"), (), ("name", "position")),
    "profiles": (("kind", "size", "profile"), (), ("kind", "size")),
    "tools": (("lane", "tool"), (), ("lane", "tool")),
}


def upgrade() -> None:
    bind = op.get_bind()
    present = set(sa.inspect(bind).get_table_names())
    if "starpulse_policy_versions" not in present:
        op.create_table(
            "starpulse_policy_versions",
            sa.Column("hash", sa.String, primary_key=True),
            sa.Column("document", sa.JSON, nullable=False),
            sa.Column("created_at", sa.Float, nullable=False),
        )
    if "starpulse_policy_active" not in present:
        op.create_table(
            "starpulse_policy_active",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
            sa.Column("hash", sa.String, sa.ForeignKey("starpulse_policy_versions.hash"), nullable=False),
            sa.Column("activated_at", sa.Float, nullable=False),
        )
    document: dict[str, list[dict[str, object]]] = {}
    for name, (columns, documents, order) in _FLAT.items():
        flat = sa.table(
            f"starpulse_policy_{name}",
            *(sa.column(column, sa.JSON) if column in documents else sa.column(column) for column in columns),
            *(sa.column(column) for column in order if column not in columns),
        )
        query = sa.select(*(flat.c[column] for column in columns)).order_by(*(flat.c[column] for column in order))
        document[name] = [dict(record._mapping) for record in bind.execute(query)] if f"starpulse_policy_{name}" in present else []
    active = sa.table("starpulse_policy_active", sa.column("id"))
    if any(document.values()) and bind.execute(sa.select(sa.func.count()).select_from(active)).scalar() == 0:
        digest = sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
        now = time.time()
        op.execute(sa.text("INSERT INTO starpulse_policy_versions (hash, document, created_at) VALUES (:hash, :document, :now)").bindparams(
            sa.bindparam("document", type_=sa.JSON), hash=digest, document=document, now=now))
        op.execute(sa.text("INSERT INTO starpulse_policy_active (id, hash, activated_at) VALUES (1, :hash, :now)").bindparams(hash=digest, now=now))


def downgrade() -> None:
    raise NotImplementedError("a policy version cannot be flattened back into the tables it replaced")
