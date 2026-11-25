"""A task's stored UUID beside its key in the tables that name a task by key: the writers fill it as they insert and the
fold of a task fills the rows that lack it."""

from collections.abc import Iterable

from sqlalchemy import Connection, ScalarSelect, bindparam, column, select, table, update
from sqlalchemy.sql.elements import ColumnElement

from starpulse.event_log.readmodel.tables import board_keys

#: Each table that names a task, by its key column.
KEYED = (
    ("starpulse_machine_events", "task"),
    ("starpulse_machine_tasks", "task"),
    ("starpulse_lane_changes", "task"),
    ("starpulse_task_verdicts", "task"),
    ("starpulse_scheduler_runs", "task"),
    ("starpulse_task_criteria", "task_id"),
)


def of(key: str | None | ColumnElement) -> ScalarSelect[str]:
    """The UUID `board_keys` gives `key`, as a value for an insert; null when it gives none."""
    return select(board_keys.c.token).where(board_keys.c.task_id == key, board_keys.c.kind == "uuid").scalar_subquery()


def fill(db: Connection, keys: Iterable[str], tables: Iterable[tuple[str, str]] = KEYED) -> None:
    """Set the UUID of each key in `tables`' rows that lack one, where `board_keys` gives the key one."""
    if not (bound := [{"key": key} for key in keys]):
        return
    named = of(bindparam("key"))
    for name, key_column in tables:
        rows = table(name, column(key_column), column("task_uuid"))
        db.execute(
            update(rows).where(rows.c[key_column] == bindparam("key"), rows.c.task_uuid.is_(None), named.is_not(None)).values(task_uuid=named),
            bound,
        )
