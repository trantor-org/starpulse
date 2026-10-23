"""A Task row as the tables hold it: `fold`'s row in, the same row out, with the criteria in their own table."""

from __future__ import annotations

from sqlalchemy import Connection, delete, insert, select
from sqlalchemy.dialects import sqlite

from starpulse._internal.readmodel.fold import Row
from starpulse._internal.readmodel.tables import criteria, tasks


def load(db: Connection, task_id: str) -> Row | None:
    """The Task's row, or None when it has none."""
    found = db.execute(select(tasks).where(tasks.c.id == task_id)).mappings().first()
    if found is None:
        return None
    items = db.execute(
        select(criteria).where(criteria.c.task_id == task_id).order_by(criteria.c.kind, criteria.c.n)
    ).mappings()
    return {key: value for key, value in found.items() if key != "seq"} | {
        "criteria": [{key: value for key, value in item.items() if key != "task_id"} for item in items]
    }


def save(db: Connection, row: Row, seq: int) -> None:
    """Replace the Task's row and criteria with `row`, folded up to stream position `seq`."""
    values = {key: value for key, value in row.items() if key != "criteria"} | {"seq": seq}
    upsert = sqlite.insert(tasks).values(**values)
    db.execute(upsert.on_conflict_do_update(index_elements=["id"], set_={key: upsert.excluded[key] for key in values if key != "id"}))
    db.execute(delete(criteria).where(criteria.c.task_id == row["id"]))
    if row["criteria"]:
        db.execute(insert(criteria), [{"task_id": row["id"]} | item for item in row["criteria"]])
