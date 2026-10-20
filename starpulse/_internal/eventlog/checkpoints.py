"""How far each reader of the log got, in one table: an integer position and, for a reader that rebuilds state, the
snapshot it rebuilds from.

A snapshot is read only when it was saved under the model's current `SCHEMA_VERSION` and still validates; otherwise the
reader gets its position and no snapshot, and replays from the log.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, ValidationError
from sqlalchemy import Connection, Engine, delete, select
from sqlalchemy.dialects import sqlite

from starpulse._internal.eventlog.tables import checkpoints


class Checkpoints:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def load(self, name: str, model: type[BaseModel] | None = None) -> tuple[int | None, BaseModel | None]:
        """The position last saved for `name` and, when `model` is given and the saved state is one it can read, the
        snapshot; (None, None) when nothing was saved. Raises when the database does."""
        c = checkpoints.c
        with self.engine.connect() as db:
            row = db.execute(select(c.position, c.schema_version, c.state).where(c.name == name)).first()
        if row is None:
            return None, None
        if model is None or row.state is None or row.schema_version != model.SCHEMA_VERSION:  # type: ignore[attr-defined]
            return row.position, None
        try:
            return row.position, model.model_validate(row.state)
        except ValidationError:
            return row.position, None

    def save(self, name: str, position: int, model: BaseModel | None = None, *, conn: Connection | None = None) -> None:
        """Keep `position` (and `model`, the state a reader built up to it) as `name`'s checkpoint, in place of the last.

        A name ending `@<hash>` also removes the checkpoints saved under the same base with another hash: a projection
        change saved under a new name, and the old row would otherwise stay forever. `conn` joins the caller's
        transaction; without it the save commits on its own.
        """
        if conn is None:
            with self.engine.begin() as db:
                self.save(name, position, model, conn=db)
            return
        values = {
            "name": name,
            "position": position,
            "schema_version": 0 if model is None else model.SCHEMA_VERSION,  # type: ignore[attr-defined]
            "state": None if model is None else model.model_dump(mode="json"),
            "saved_at": time.time(),
        }
        insert = sqlite.insert(checkpoints).values(**values)
        conn.execute(
            insert.on_conflict_do_update(
                index_elements=["name"], set_={key: insert.excluded[key] for key in values if key != "name"}
            )
        )
        base, at, _ = name.rpartition("@")
        if at:
            superseded = checkpoints.c.name.startswith(base + at, autoescape=True) & (checkpoints.c.name != name)
            conn.execute(delete(checkpoints).where(superseded))
