"""The projector: folds Task Events into the read model and remembers how far it got."""

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import Connection, Engine, delete, select
from sqlalchemy.dialects import sqlite

from starpulse.contracts.adapters import TaskKeys
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.readmodel import rows
from starpulse.event_log.readmodel.fold import Row, apply
from starpulse.event_log.readmodel.machine_fold import Placer, event_of
from starpulse.event_log.readmodel.tables import criteria, machine_tasks, tasks
from starpulse.event_log.store import EventStore, StoredEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import EventLog

CHECKPOINT = "read-model:tasks"
#: How far the projector has folded `machine:events` into `starpulse_machine_tasks`; it commits with each batch's rows.
MACHINE_CHECKPOINT = "read-model:machine-tasks"
#: How far the search index holds the read model, apart from `CHECKPOINT`: any process may fold a row, and only the one
#: holding the index writes its search row. The name carries the lane rule, so a rule change reindexes every row.
SEARCH_CHECKPOINT = "read-model:search-comments"
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
        comments: str = "",
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
        """Fold every Task Event and machine event appended since the last checkpoints and index the rows for search; the
        number of Task Events folded."""
        folded = self.fold_tasks()
        self.fold_machines()
        self.index()
        return folded

    def fold_tasks(self) -> int:
        """Fold every Task Event appended since the last checkpoint; the number folded, so a new Task's row waits for
        no machine fold or search index.

        Each batch commits its rows and the checkpoint together, so a stop between batches resumes at the next Event
        and a stop inside one folds nothing.
        """
        return self._fold_tasks(resident=False)

    def index(self) -> None:
        """Make the search index hold every row folded since it last did; nothing without a search index."""
        if self._search is not None:
            self._index_changed()

    def rebuild(self) -> int:
        """Drop every row and the checkpoint and fold the whole History again; the number of Events folded.

        The tables are empty, so the rows stay in memory through the fold and are written once at its end: a stop inside
        it leaves them empty and the checkpoints at 0, which the next `catch_up` folds from the start."""
        with self._engine.begin() as db:
            db.execute(delete(criteria))
            db.execute(delete(tasks))
            db.execute(delete(machine_tasks))
            self._checkpoints.save(CHECKPOINT, 0, conn=db)
            self._checkpoints.save(MACHINE_CHECKPOINT, 0, conn=db)
            self._checkpoints.save(SEARCH_CHECKPOINT, 0, conn=db)
        folded = self._fold_tasks(resident=True)
        self._fold_machines(resident=True)
        self.index()
        return folded

    def _fold_tasks(self, *, resident: bool) -> int:
        """Fold every Task Event past the checkpoint, a batch at a time; `resident` keeps every row in memory and writes
        them with the checkpoint once the History is read, which only an empty table allows."""
        position, _ = self._checkpoints.load(CHECKPOINT)
        position = position or 0
        held: dict[str, tuple[Row | None, int]] = {}
        folded = 0
        while batch := self._store.read_after("task", position, BATCH):
            position = batch[-1].position
            folded += len(batch)
            if resident:
                self._fold(batch, held, lambda _: (None, 0))
                continue
            folded_rows: dict[str, tuple[Row | None, int]] = {}
            with self._engine.begin() as db:
                self._fold(batch, folded_rows, lambda task: rows.load_at(db, task))
                rows.save_all(db, folded_rows.values())
                self._checkpoints.save(CHECKPOINT, position, conn=db)
        if resident and held:
            with self._engine.begin() as db:
                rows.save_all(db, held.values())
                self._checkpoints.save(CHECKPOINT, position, conn=db)
        return folded

    def fold_machines(self) -> None:
        """Fold every `machine:events` entry past the machine checkpoint into `starpulse_machine_tasks`, a batch at a time."""
        self._fold_machines(resident=False)

    def _fold_machines(self, *, resident: bool) -> None:
        """The fold of `fold_machines`; `resident` as in `_fold_tasks`."""
        if self._log is None or self._placer is None:
            return
        from starpulse.event_log.event_log import Tail  # noqa: PLC0415 - the log's stack loads when a log opens
        from starpulse.event_log.events import STREAM  # noqa: PLC0415

        position, _ = self._checkpoints.load(MACHINE_CHECKPOINT)
        tail = Tail(self._log, STREAM, after=position or 0, batch=BATCH)
        held: dict[tuple[str, str], tuple[dict, int]] = {}
        last = position or 0
        while batch := tail.poll_json():
            last = batch[-1][0]
            if resident:
                self._place(batch, held, lambda *_: (None, 0))
                continue
            placed: dict[tuple[str, str], tuple[dict, int]] = {}
            with self._engine.begin() as db:
                self._place(batch, placed, lambda *key: self._load_machine(db, *key))
                self._save_machines(db, placed)
                self._checkpoints.save(MACHINE_CHECKPOINT, last, conn=db)
        if resident and held:
            with self._engine.begin() as db:
                self._save_machines(db, held)
                self._checkpoints.save(MACHINE_CHECKPOINT, last, conn=db)

    def _place(
        self,
        batch: Sequence[tuple[int, str]],
        touched: dict[tuple[str, str], tuple[dict, int]],
        load: Callable[..., tuple[dict | None, int]],
    ) -> None:
        """Place each machine event on its task in `touched`, the batch's later events seeing the earlier ones. `load`
        gives a task's agent and entry when `touched` lacks it.

        A row remembers the entry it last folded (`seq`): an entry at or before it was folded already, so a stream read
        again (a second reader, a checkpoint reset) leaves each trail step once.
        """
        for entry_id, fields in batch:
            event = event_of(fields)
            if event is None:
                continue
            key = (event.machine, event.task or event.run or "")
            before, seq = touched[key] if key in touched else load(*key)
            if entry_id <= seq:
                continue
            placed = self._placer.place(before, event)
            if placed is not None:
                flow, task, agent = placed
                touched[flow, task] = (agent, entry_id)

    @staticmethod
    def _save_machines(db: Connection, placed: Mapping[tuple[str, str], tuple[dict, int]]) -> None:
        """Save each placed task's row once."""
        if not placed:
            return
        values = [
            {
                "machine": flow,
                "task": task,
                "state": agent["state"],
                "agent": agent,
                "active_at": agent["active"],
                "seq": seq,
            }
            for (flow, task), (agent, seq) in placed.items()
        ]
        upsert = sqlite.insert(machine_tasks)
        set_ = {column: upsert.excluded[column] for column in values[0] if column not in ("machine", "task")}
        db.execute(upsert.on_conflict_do_update(index_elements=["machine", "task"], set_=set_), values)

    @staticmethod
    def _load_machine(db: Connection, machine: str, task: str) -> tuple[dict | None, int]:
        """The agent a machine last placed the task as and the entry that placed it, or (None, 0) when it has no row."""
        row = db.execute(
            select(machine_tasks.c.agent, machine_tasks.c.seq).where(
                machine_tasks.c.machine == machine, machine_tasks.c.task == task
            )
        ).first()
        return (row.agent, row.seq) if row else (None, 0)

    @staticmethod
    def _fold(
        batch: list[StoredEvent],
        held: dict[str, tuple[Row | None, int]],
        load: Callable[[str], tuple[Row | None, int]],
    ) -> None:
        """Fold each Event onto its Task's row in `held`, loading a row it lacks. A row
        remembers the position it last folded (`seq`): an Event at or before it was folded already, so a second reader
        from a stale checkpoint adds nothing."""
        for event in batch:
            task = event.subject_id
            row, seq = held[task] if task in held else load(task)
            if event.position <= seq:
                continue
            held[task] = (apply(row, event), event.position)

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
            comments="\n".join(comment["text"] for comment in row["comments"]),
            lane="archived" if row["archived"] and not done else row["state"],
            labels=row["labels"],
            finished_at=row["updated_at"] if finished else None,
            connection=db,
        )
