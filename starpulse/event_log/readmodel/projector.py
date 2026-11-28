"""The projector: folds Task Events into the read model and remembers how far it got."""

from collections.abc import Callable, Collection, Mapping, Sequence
from functools import cached_property
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects import sqlite

from starpulse.contracts.adapters import TaskKeys
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.readmodel import card_fields, rows, task_uuid
from starpulse.event_log.readmodel.fold import Row, apply
from starpulse.event_log.readmodel.machine_fold import Placer, event_of
from starpulse.event_log.readmodel.tables import machine_tasks, tasks
from starpulse.event_log.store import EventStore, StoredEvent
from starpulse.machine_engine.model.state_roles import StateRoles

if TYPE_CHECKING:
    from starpulse.event_log.event_log import EventLog, Tail
lazy from starpulse.event_log.events import STREAM

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
        roles: StateRoles | None = None,
    ) -> None:
        self._engine = engine
        self._store = store
        self._search = search
        self._log = log
        self._keys = keys
        self._drawn = drawn
        #: The roles a card's phase and open-dependency count read: the board's own, unless given. None with no board drawn.
        self._roles = roles or (StateRoles.of_drawn(drawn["board"]) if drawn and "board" in drawn else None)
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
        return self._fold_tasks()

    def index(self) -> None:
        """Make the search index hold every row folded since it last did; nothing without a search index."""
        if self._search is not None:
            self._index_changed()

    def rebuild(self, tasks: Collection[str]) -> list[str]:
        """Replay: replace each named Task's row with one folded from its whole History; the Tasks replaced.

        The one fold that starts from a Task's first Event, run only by `starpulse replay` for an operator. It reads and
        saves under the write lock, so no Event folds between the two, and it touches no checkpoint and no other Task.
        """
        held: dict[str, tuple[Row | None, int]] = {}
        with self._engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            for task in tasks:
                self._fold(self._store.read_in(db, "task", task), held, lambda _: (None, 0))
            rows.save_all(db, held.values())
            self._restate(db, held)
        return sorted(held)

    def restate_all(self) -> None:
        """Restate every task's card fields: what a store folded before they were kept holds none until its task changes."""
        with self._engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            ids = list(db.execute(select(tasks.c.id)).scalars())
            for start in range(0, len(ids), BATCH):
                self._restate(db, ids[start : start + BATCH])

    def _restate(self, db: Connection, folded: Collection[str]) -> None:
        card_fields.restate(db, folded, self._drawn, self._roles)

    def _tail(self, after: int) -> Tail:
        from starpulse.event_log.event_log import Tail  # noqa: PLC0415 - the log's stack loads when a log opens

        return Tail(self._log, STREAM, after=after, batch=BATCH)

    def _fold_tasks(self) -> int:
        """Fold every Task Event past the checkpoint, a batch at a time; the number folded."""
        position, _ = self._checkpoints.load(CHECKPOINT)
        position = position or 0
        folded = 0
        while batch := self._store.read_after("task", position, BATCH):
            folded_rows: dict[str, tuple[Row | None, int]] = {}
            with self._engine.begin() as db:
                db.exec_driver_sql("BEGIN IMMEDIATE")  # a second folder waits here, so the comparison below holds through the write
                if (self._checkpoints.load(CHECKPOINT, conn=db)[0] or 0) != position:
                    break  # another folder took this batch: the next pass folds from its cursor
                self._fold(batch, folded_rows, lambda task: rows.load_at(db, task))
                rows.save_all(db, folded_rows.values())
                self._restate(db, folded_rows)
                position = batch[-1].position
                self._checkpoints.save(CHECKPOINT, position, conn=db)
            folded += len(batch)
        return folded

    def fold_machines(self) -> None:
        """Fold every `machine:events` entry past the machine checkpoint into `starpulse_machine_tasks`, a batch at a time."""
        if self._log is None or self._drawn is None:
            return
        position, _ = self._checkpoints.load(MACHINE_CHECKPOINT)
        tail = self._tail(position or 0)
        while batch := tail.poll_json():
            placed: dict[tuple[str, str], tuple[dict, int]] = {}
            with self._engine.begin() as db:
                self._place(batch, placed, lambda *key: self._load_machine(db, *key))
                self._save_machines(db, placed)
                card_fields.restate_phase(db, {task for _, task in placed}, self._drawn, self._roles)
                self._checkpoints.save(MACHINE_CHECKPOINT, batch[-1][0], conn=db)

    @cached_property
    def _placer(self) -> Placer:
        # Built at the first machine event, so a projector that folds none never builds its machines' tables.
        assert self._drawn is not None  # fold_machines returns before any event without them
        return Placer(self._drawn, self._keys)

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
        task_uuid.fill(db, {task for _, task in placed}, tables=[("starpulse_machine_tasks", "task")])

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
