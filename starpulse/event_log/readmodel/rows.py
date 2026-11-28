"""A Task row as the tables hold it: `fold`'s row in, the same row out, with the criteria in their own table."""

from collections.abc import Iterable

from sqlalchemy import Connection, and_, bindparam, delete, func, insert, or_, select
from sqlalchemy.dialects import sqlite

from starpulse.event_log.readmodel import task_uuid
from starpulse.event_log.readmodel.card_fields import STORED
from starpulse.event_log.readmodel.fold import Row
from starpulse.event_log.readmodel.tables import board_keys, criteria, tasks


#: Built once, so a read pays neither building the statement nor its cache key, which cost more than running it.
_TASK = select(tasks).where(tasks.c.id == bindparam("id"))
_IN_ORDER = (criteria.c.kind, criteria.c.n)
_CRITERIA = select(criteria).where(criteria.c.task_id == bindparam("id")).order_by(*_IN_ORDER)
#: A renamed task's criteria follow its UUID; a criterion of another UUID is not told by the key it once held.
_UUID_CRITERIA = (
    select(criteria)
    .where(or_(and_(criteria.c.task_id == bindparam("id"), criteria.c.task_uuid.is_(None)), criteria.c.task_uuid == bindparam("uuid")))
    .order_by(*_IN_ORDER)
)


def load(db: Connection, task_id: str) -> Row | None:
    """The Task's row, or None when it has none."""
    return load_at(db, task_id)[0]


def load_any_case(db: Connection, task_id: str) -> Row | None:
    """The Task's row under the id that spells `task_id` in any case, or None when it has none."""
    spelled = db.execute(select(tasks.c.id).where(func.lower(tasks.c.id) == task_id.lower())).scalar()
    return None if spelled is None else load(db, spelled)


def load_at(db: Connection, task_id: str) -> tuple[Row | None, int]:
    """The Task's row and the position of the last Event folded into it, or (None, 0) when it has no row."""
    found = db.execute(_TASK, {"id": task_id}).mappings().first()
    if found is None:
        return None, 0
    items = db.execute(_UUID_CRITERIA if found["uuid"] else _CRITERIA, {"id": task_id, "uuid": found["uuid"]}).mappings()
    row = {key: value for key, value in found.items() if key not in ("seq", "uuid", *STORED)} | {
        "criteria": [{key: value for key, value in item.items() if key not in ("task_id", "task_uuid")} for item in items]
    }
    return row, found["seq"]


def after(db: Connection, seq: int, limit: int) -> list[tuple[Row, int]]:
    """Up to `limit` rows folded past stream position `seq`, oldest first, each with the position it was folded to."""
    found = db.execute(select(tasks.c.id, tasks.c.seq).where(tasks.c.seq > seq).order_by(tasks.c.seq).limit(limit))
    return [(row, position) for task_id, position in found.all() if (row := load(db, task_id)) is not None]


def save_all(db: Connection, folded: Iterable[tuple[Row, int]]) -> None:
    """Replace each Task's row and criteria with its row, folded up to its stream position: one statement per table."""
    items = list(folded)
    if not items:
        return
    values = [
        {key: value for key, value in row.items() if key != "criteria"}
        | {"seq": seq, "uuid": (row["meta"] or {}).get("uuid") or ""}
        for row, seq in items
    ]
    upsert = sqlite.insert(tasks)
    db.execute(
        upsert.on_conflict_do_update(index_elements=["id"], set_={key: upsert.excluded[key] for key in values[0] if key != "id"}),
        values,
    )
    db.execute(delete(criteria).where(criteria.c.task_id == bindparam("task")), [{"task": row["id"]} for row, _ in items])
    if numbered := [{"task_id": row["id"]} | item for row, _ in items for item in row["criteria"]]:
        db.execute(insert(criteria), numbered)
    db.execute(delete(board_keys).where(board_keys.c.task_id == bindparam("task")), [{"task": row["id"]} for row, _ in items])
    names = [
        {"token": token, "task_id": row["id"], "kind": kind}
        for row, _ in items
        for kind, tokens in (("uuid", [row["meta"].get("uuid")]), ("alias", row["meta"].get("aliases") or []))
        for token in tokens
        if token
    ]
    if names:
        keys = sqlite.insert(board_keys)
        db.execute(keys.on_conflict_do_update(index_elements=["token"], set_={"task_id": keys.excluded.task_id, "kind": keys.excluded.kind}), names)
    task_uuid.fill(db, [row["id"] for row, _ in items])
