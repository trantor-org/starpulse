"""Store each task's History and retired row under its canonical `TASK-N` key.

A retire and an import wrote the id as its file spelled it, so 959 tasks have a `task-N` stream and retired row. The
read side folds the cases; this moves the rows to `TASK-N`, the one prefix the store keys tasks by. A lowercase stream whose uppercase twin exists is renumbered after the
twin's head in its own order, keeping each Event's id and time.

Revision ID: 0068
Revises: 0067
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: str | tuple[str, ...] | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENTS = sa.table(
    "starpulse_stream_events",
    sa.column("id", sa.Integer),
    sa.column("subject_kind", sa.String),
    sa.column("subject_id", sa.String),
    sa.column("version", sa.Integer),
)
_RETIRED = sa.table("starpulse_retired_tasks", sa.column("task", sa.String))


def upgrade() -> None:
    bind = op.get_bind()
    lower = sa.and_(_EVENTS.c.subject_kind == "task", _EVENTS.c.subject_id.op("GLOB")("task-*"))
    for key in bind.execute(sa.select(_EVENTS.c.subject_id).where(lower).distinct()).scalars().all():
        canonical = f"TASK-{key[5:]}"
        head = bind.execute(
            sa.select(sa.func.coalesce(sa.func.max(_EVENTS.c.version), 0)).where(
                _EVENTS.c.subject_kind == "task", _EVENTS.c.subject_id == canonical
            )
        ).scalar_one()
        rows = (
            bind.execute(
                sa.select(_EVENTS.c.id)
                .where(_EVENTS.c.subject_kind == "task", _EVENTS.c.subject_id == key)
                .order_by(_EVENTS.c.version)
            )
            .scalars()
            .all()
        )
        for offset, row in enumerate(rows, 1):
            bind.execute(
                _EVENTS.update().where(_EVENTS.c.id == row).values(subject_id=canonical, version=head + offset)
            )
    bind.execute(
        _RETIRED.update()
        .where(_RETIRED.c.task.op("GLOB")("task-*"))
        .values(task=sa.literal("TASK-") + sa.func.substr(_RETIRED.c.task, 6))
    )


def downgrade() -> None:
    raise NotImplementedError("the rows keep no record of the case they were stored in")
