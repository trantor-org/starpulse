"""A task's pull request links: each stored with its `link-written` event, keyed by the task's UUID.

A link is a row of `task_links` and an event on the `task-link` stream of the same UUID, committed in one transaction, so
a rename of the task's key moves neither. Only the task actor writes one, on the request of the session that holds the task.
"""

from dataclasses import dataclass

from sqlalchemy import Connection, Engine, delete, insert, select
from sqlalchemy.exc import IntegrityError

from starpulse.event_log.store import EventStore, NewEvent
from starpulse.event_log.tables import task_links

__all__ = ["DeliveredElsewhere", "StoredLink", "TaskLinks"]

KIND = "task-link"
WRITER = "task-actor"


@dataclass(frozen=True)
class StoredLink:
    task: str
    role: str
    ref: str
    requested_by: str
    at: float
    event: str


class DeliveredElsewhere(Exception):
    """The pull request already delivers another task, named by its UUID."""

    def __init__(self, task: str) -> None:
        super().__init__(task)
        self.task = task


class TaskLinks:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._events = EventStore(engine)

    def put(self, task: str, role: str, ref: str, requested_by: str) -> tuple[StoredLink, bool]:
        """Store `ref` as a `role` link of the task with UUID `task`: the link and whether this call wrote it.

        A link already stored is returned unwritten. A `delivers` link of a pull request another task delivers raises
        `DeliveredElsewhere`, also when two requests race for it and the store's unique index refuses the second;
        `StaleVersion` is raised when the stream moved, and the caller sends again."""
        try:
            return self._put(task, role, ref, requested_by)
        except IntegrityError:
            with self._engine.connect() as db:
                other = db.execute(select(task_links.c.task).where(task_links.c.ref == ref, task_links.c.role == role)).scalar()
            if role == "delivers" and other not in (None, task):
                raise DeliveredElsewhere(other) from None
            raise

    def _put(self, task: str, role: str, ref: str, requested_by: str) -> tuple[StoredLink, bool]:
        with self._engine.begin() as db:
            if (row := _row(db, task, role, ref)) is not None:
                return row, False
            if role == "delivers":
                other = db.execute(
                    select(task_links.c.task).where(task_links.c.ref == ref, task_links.c.role == role)
                ).scalar()
                if other is not None:
                    raise DeliveredElsewhere(other)
            payload = {"role": role, "ref": ref, "requestedBy": requested_by}
            stored = self._events.append(
                KIND, task, self._events.head_in(db, KIND, task), [NewEvent("link-written", payload, requested_by, WRITER)],
                connection=db,
            )[0]
            db.execute(insert(task_links).values(task=task, role=role, ref=ref, requested_by=requested_by, at=stored.at, event_id=stored.event_id))
            return StoredLink(task, role, ref, requested_by, stored.at, stored.event_id), True

    def remove(self, task: str, role: str, ref: str, requested_by: str) -> StoredLink | None:
        """Remove the link and answer it as it was, or None when the task has no such link."""
        with self._engine.begin() as db:
            if (row := _row(db, task, role, ref)) is None:
                return None
            payload = {"role": role, "ref": ref, "requestedBy": requested_by}
            self._events.append(
                KIND, task, self._events.head_in(db, KIND, task), [NewEvent("link-removed", payload, requested_by, WRITER)],
                connection=db,
            )
            db.execute(delete(task_links).where(task_links.c.task == task, task_links.c.role == role, task_links.c.ref == ref))
            return row


def _row(db: Connection, task: str, role: str, ref: str) -> StoredLink | None:
    found = db.execute(
        select(task_links).where(task_links.c.task == task, task_links.c.role == role, task_links.c.ref == ref)
    ).one_or_none()
    return None if found is None else StoredLink(found.task, found.role, found.ref, found.requested_by, found.at, found.event_id)
