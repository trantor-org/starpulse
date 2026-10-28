"""The projector: folds Task Events into the read model and remembers how far it got."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import Connection, Engine, delete

from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.readmodel import rows
from starpulse.event_log.readmodel.fold import fold
from starpulse.event_log.readmodel.tables import criteria, tasks
from starpulse.event_log.store import EventStore, StoredEvent

CHECKPOINT = "read-model:tasks"
#: How far the search index holds the read model, apart from `CHECKPOINT`: any process may fold a row, and only the one
#: holding the index writes its search row.
SEARCH_CHECKPOINT = "read-model:search"
#: The states in which a task has finished, as the search index dates it.
_FINISHED = frozenset({"done", "archived"})
BATCH = 500


class SearchIndex(Protocol):
    """What the projector needs of a search index: a context's index implements it, so the kernel imports no context."""

    def index_fields(
        self,
        task_id: str,
        *,
        title: str,
        description: str,
        criteria: Sequence[str],
        notes: str,
        lane: str,
        labels: Sequence[str],
        finished_at: float | None = None,
        connection: Connection | None = None,
    ) -> None: ...


class Projector:
    def __init__(self, engine: Engine, store: EventStore, search: SearchIndex | None = None) -> None:
        self._engine = engine
        self._store = store
        self._search = search
        self._checkpoints = Checkpoints(engine)

    def catch_up(self) -> int:
        """Fold every Task Event appended since the last checkpoint; the number folded.

        Each batch commits its rows and the checkpoint together, so a stop between batches resumes at the next Event
        and a stop inside one folds nothing.
        """
        position, _ = self._checkpoints.load(CHECKPOINT)
        folded = 0
        while batch := self._store.read_after("task", position or 0, BATCH):
            position = batch[-1].position
            with self._engine.begin() as db:
                self._fold(db, batch)
                self._checkpoints.save(CHECKPOINT, position, conn=db)
            folded += len(batch)
        if self._search is not None:
            self._index_changed()
        return folded

    def rebuild(self) -> int:
        """Drop every row and the checkpoint and fold the whole History again; the number of Events folded."""
        with self._engine.begin() as db:
            db.execute(delete(criteria))
            db.execute(delete(tasks))
            self._checkpoints.save(CHECKPOINT, 0, conn=db)
            self._checkpoints.save(SEARCH_CHECKPOINT, 0, conn=db)
        return self.catch_up()

    def _fold(self, db, batch: list[StoredEvent]) -> None:
        touched: dict[str, tuple[dict | None, int]] = {}
        for event in batch:
            row = touched[event.subject_id][0] if event.subject_id in touched else rows.load(db, event.subject_id)
            touched[event.subject_id] = (fold(row, event), event.position)
        for row, seq in touched.values():
            rows.save(db, row, seq)

    def _index_changed(self) -> None:
        """Make the search index hold every row folded since it last did, by whichever process folded it."""
        position, _ = self._checkpoints.load(SEARCH_CHECKPOINT)
        while batch := self._read_after(position or 0):
            position = batch[-1][1]
            with self._engine.begin() as db:
                for row, _ in batch:
                    self._index(db, row)
                self._checkpoints.save(SEARCH_CHECKPOINT, position, conn=db)

    def _read_after(self, position: int) -> list[tuple[dict, int]]:
        with self._engine.connect() as db:
            return rows.after(db, position, BATCH)

    def _index(self, db: Connection, row: dict) -> None:
        """Make the search index hold the Task's row: an archived Task is found in the archived lane."""
        finished = row["archived"] or row["state"].lower() in _FINISHED
        self._search.index_fields(
            row["id"],
            title=row["title"],
            description=row["description"],
            criteria=[item["text"] for item in row["criteria"] if item["kind"] == "ac"],
            notes=row["notes"],
            lane="archived" if row["archived"] else row["state"],
            labels=row["labels"],
            finished_at=row["updated_at"] if finished else None,
            connection=db,
        )
