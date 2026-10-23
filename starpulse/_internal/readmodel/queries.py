"""The statements that read the Task tables: each is one index seek or one bounded index range, never a table scan.

`ReadModel` runs them; the tests EXPLAIN them. Archived Tasks stay out of every live query by the `archived = 0`
predicate the partial indexes carry, so the cost of a read follows the live board, not the whole History.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, column, exists, false, func, or_, select

from starpulse._internal.readmodel.tables import tasks

SUMMARY = (
    tasks.c.id,
    tasks.c.seq,
    tasks.c.version,
    tasks.c.title,
    tasks.c.type,
    tasks.c.state,
    tasks.c.priority,
    tasks.c.milestone,
    tasks.c.assignee,
    tasks.c.archived,
    tasks.c.labels,
    tasks.c.updated_at,
)


def snapshot(state: str | None = None) -> Select[Any]:
    """The unarchived Tasks, in id order, narrowed to `state` when given."""
    query = select(*SUMMARY).where(tasks.c.archived == false()).order_by(tasks.c.id)
    return query if state is None else query.where(tasks.c.state == state)


def with_field(field_column: str, value: object) -> Select[Any]:
    """The ids of unarchived Tasks whose declared, queried field's generated column equals `value`."""
    return select(tasks.c.id).where(tasks.c.archived == false(), column(field_column) == value).order_by(tasks.c.id)


def ready(state: str, done: str) -> Select[Any]:
    """The ids of unarchived Tasks in `state` none of whose dependencies is outside `done`.

    A dependency with no row blocks too: it is a Task the board has not imported yet.
    """
    dependency = func.json_each(tasks.c.dependencies).table_valued("value").alias("dependency")
    target = tasks.alias("target")
    blocked = (
        select(1)
        .select_from(dependency.outerjoin(target, target.c.id == dependency.c.value))
        .where(or_(target.c.id.is_(None), target.c.state != done))
    )
    return (
        select(tasks.c.id)
        .where(tasks.c.archived == false(), tasks.c.state == state, ~exists(blocked.correlate(tasks)))
        .order_by(tasks.c.id)
    )


def since(seq: int, limit: int) -> Select[Any]:
    """The Tasks changed after stream position `seq`, archived ones included, oldest change first."""
    return select(*SUMMARY).where(tasks.c.seq > seq).order_by(tasks.c.seq).limit(limit)
