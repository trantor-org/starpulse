"""How far each reader of the log got, in one table: an integer position and, for a reader that rebuilds state, the
snapshot it rebuilds from.

A snapshot is read only when it still validates against the model; otherwise the reader gets its position and no
snapshot, and replays from the log. A name is one checkpoint: a projection that changes keeps no cursor here, because
its family refolds under its own stamp.
"""

import time

from pydantic import BaseModel, ValidationError
from sqlalchemy import Connection, Engine, func, or_, select
from sqlalchemy.dialects import sqlite

from starpulse.event_log.tables import checkpoints


class Checkpoints:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def load(
        self, name: str, model: type[BaseModel] | None = None, *, conn: Connection | None = None
    ) -> tuple[int | None, BaseModel | None]:
        """The position last saved for `name` and, when `model` is given and the saved state is one it can read, the
        snapshot; (None, None) when nothing was saved. `conn` reads inside the caller's transaction. Raises when the
        database does."""
        c = checkpoints.c
        if conn is None:
            with self.engine.connect() as db:
                return self.load(name, model, conn=db)
        row = conn.execute(select(c.position, c.state).where(c.name == name)).first()
        if row is None:
            return None, None
        if model is None or row.state is None:
            return row.position, None
        try:
            return row.position, model.model_validate(row.state)
        except ValidationError:
            return row.position, None

    def save(self, name: str, position: int, model: BaseModel | None = None, *, conn: Connection | None = None) -> None:
        """Keep `position` (and `model`, the state a reader built up to it) as `name`'s checkpoint, in place of the last.
        `conn` joins the caller's transaction; without it the save commits on its own."""
        if conn is None:
            with self.engine.begin() as db:
                self.save(name, position, model, conn=db)
            return
        values = {
            "name": name,
            "position": position,
            "state": None if model is None else model.model_dump(mode="json"),
            "saved_at": time.time(),
        }
        insert = sqlite.insert(checkpoints).values(**values)
        conn.execute(
            insert.on_conflict_do_update(
                index_elements=["name"],
                set_={key: insert.excluded[key] for key in values if key != "name"},
                where=or_(
                    checkpoints.c.position != insert.excluded.position,
                    func.json(checkpoints.c.state).is_not(func.json(insert.excluded.state)),
                ),
            )
        )
