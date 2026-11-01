"""The projector: folds Task Events into the read model and remembers how far it got."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import Connection, Engine, delete, select
from sqlalchemy.dialects import sqlite

from starpulse.contracts.adapters import TaskKeys
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.readmodel import rows
from starpulse.event_log.readmodel.fold import fold
from starpulse.event_log.readmodel.machine_fold import Placer, event_of
from starpulse.event_log.readmodel.tables import criteria, machine_tasks, tasks
from starpulse.event_log.store import EventStore, StoredEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

CHECKPOINT = "read-model:tasks"
#: How far the projector has folded `machine:events` into `starpulse_machine_tasks`; it commits with each batch's rows.
MACHINE_CHECKPOINT = "read-model:machine-tasks"
#: How far the search index holds the read model, apart from `CHECKPOINT`: any process may fold a row, and only the one
#: holding the index writes its search row. The name carries the lane rule, so a rule change reindexes every row.
SEARCH_CHECKPOINT = "read-model:search-done-lane"
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
    """Folds Task History into `starpulse_tasks` and, given the log and the machines the page draws, `machine:events`
    into `starpulse_machine_tasks`. Only the Board child builds one with a log."""

    def __init__(
        self,
        engine: Engine,
        store: EventStore,
        search: SearchIndex | None = None,
        *,
        log: EventLog | None = None,
        drawn: Mapping[str, dict] | None = None,
        keys: TaskKeys | None = None,
    ) -> None:
        self._engine = engine
        self._store = store
        self._search = search
        self._log = log
        self._placer = Placer(drawn, keys) if drawn is not None else None
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
        self._fold_machines()
        if self._search is not None:
            self._index_changed()
        return folded

    def rebuild(self) -> int:
        """Drop every row and the checkpoint and fold the whole History again; the number of Events folded."""
        with self._engine.begin() as db:
            db.execute(delete(criteria))
            db.execute(delete(tasks))
            db.execute(delete(machine_tasks))
            self._checkpoints.save(CHECKPOINT, 0, conn=db)
            self._checkpoints.save(MACHINE_CHECKPOINT, 0, conn=db)
            self._checkpoints.save(SEARCH_CHECKPOINT, 0, conn=db)
        return self.catch_up()

    def _fold_machines(self) -> None:
        """Fold every `machine:events` entry past the machine checkpoint into `starpulse_machine_tasks`, a batch at a time."""
        if self._log is None or self._placer is None:
            return
        from starpulse.event_log.event_log import Tail  # noqa: PLC0415 - the log's stack loads when a log opens
        from starpulse.event_log.events import STREAM  # noqa: PLC0415

        position, _ = self._checkpoints.load(MACHINE_CHECKPOINT)
        tail = Tail(self._log, STREAM, after=position or 0, batch=BATCH)
        while batch := tail.poll():
            with self._engine.begin() as db:
                self._place(db, batch)
                self._checkpoints.save(MACHINE_CHECKPOINT, batch[-1].id, conn=db)

    def _place(self, db: Connection, batch: Sequence[Entry]) -> None:
        """Place each machine event on its task, the batch's later events seeing the earlier ones, then save each row once."""
        touched: dict[tuple[str, str], tuple[dict, int]] = {}
        for entry in batch:
            event = event_of(entry.fields)
            if event is None:
                continue
            key = (event.machine, event.task or event.run or "")
            before = touched[key][0] if key in touched else self._load_machine(db, *key)
            placed = self._placer.place(before, event)
            if placed is not None:
                flow, task, agent = placed
                touched[flow, task] = (agent, entry.id)
        for (flow, task), (agent, seq) in touched.items():
            values = {
                "machine": flow,
                "task": task,
                "state": agent["state"],
                "agent": agent,
                "active_at": agent["active"],
                "seq": seq,
            }
            upsert = sqlite.insert(machine_tasks).values(**values)
            set_ = {column: upsert.excluded[column] for column in values if column not in ("machine", "task")}
            db.execute(upsert.on_conflict_do_update(index_elements=["machine", "task"], set_=set_))

    @staticmethod
    def _load_machine(db: Connection, machine: str, task: str) -> dict | None:
        """The agent a machine last placed the task as, or None when it has no row for it."""
        return db.execute(
            select(machine_tasks.c.agent).where(machine_tasks.c.machine == machine, machine_tasks.c.task == task)
        ).scalar()

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
        """Make the search index hold the Task's row: an archived Task is found in the archived lane, unless it is Done."""
        done = row["state"].lower() == "done"
        finished = row["archived"] or row["state"].lower() in _FINISHED
        self._search.index_fields(
            row["id"],
            title=row["title"],
            description=row["description"],
            criteria=[item["text"] for item in row["criteria"] if item["kind"] == "ac"],
            notes=row["notes"],
            lane="archived" if row["archived"] and not done else row["state"],
            labels=row["labels"],
            finished_at=row["updated_at"] if finished else None,
            connection=db,
        )
