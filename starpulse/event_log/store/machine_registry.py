"""The machine registry: every compiled definition kept by its hash, one active per machine.

A command is validated against the active version and its Event records that version's hash, so a replay reads each
Event under the definition that wrote it. A change that drops a State holding live Tasks is accepted only with a
`migrations` mapping, and then every affected Task gets a `Remapped` Event in the same transaction that activates the
new version: one stale Task rolls the whole change back.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from starpulse.event_log.store.event_store import EventStore, NewEvent, StaleVersion, StoredEvent
from starpulse.event_log.store.tables import machine_active, machine_versions
from starpulse.machine_engine.adapters.machine_loader import validate
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError, compile_document
from starpulse.machine_engine.model.machine_namespace import definition_of
from starpulse.machine_engine.model.transitions import lane_id

#: The machine that moves Tasks; the one a Task stream is validated and stamped under.
TASK_MACHINE = "board"


def active_version(db: Connection, machine: str) -> str | None:
    """The hash of the version `machine` runs under, read on `db`; None before its first activation."""
    return db.execute(select(machine_active.c.hash).where(machine_active.c.machine == machine)).scalar()


#: The payload field of each Event that names a State.
_STATE_FIELD = {"TaskCreated": "state", "TaskImported": "state", "Transitioned": "to"}


class StrandedTasks(MachineDefinitionError):
    """A definition that drops a State live Tasks hold, with no `migrations` mapping for it."""


class StaleBase(MachineDefinitionError):
    """A write named a base version that is no longer the active one of its machine, or none where one is active."""


class MissingMachine(LookupError):
    """No active machine has the name."""


class RefusedRetire(MachineDefinitionError):
    """A machine that cannot go while the store relies on it."""


_ANY = object()


@dataclass(frozen=True)
class LiveTask:
    """A Task the change must carry across: its id, State as the Task holds it (a State id or a Backlog display name,
    such as `In Progress`) and the stream head the caller read it at. An archived Task keeps the definition version it
    was archived under, so activation neither checks nor remaps it."""

    id: str
    state: str
    version: int
    archived: bool = False


class MachineRegistry:
    def __init__(self, engine: Engine, store: EventStore) -> None:
        self._engine = engine
        self._store = store

    def activate(
        self,
        document: Mapping[str, Any],
        live: Sequence[LiveTask],
        *,
        base: str | None | object = _ANY,
        within: Callable[[Connection], None] | None = None,
    ) -> str:
        """Make `document` the active version of its machine and return its hash; a document that is already active
        changes nothing. `base` is the hash the caller read as active (None for no active version): another one raises
        `StaleBase`. `within` runs in the activating transaction, so what it writes lands with the version or not at all.
        Raises `StrandedTasks` naming the States and Tasks a missing mapping strands, and `StaleVersion` when a live
        Task moved since it was read; each leaves the active version as it was."""
        validate(document)
        name = document["name"]
        compile_document(dict(document), Path(name))
        digest = definition_of(document).digest
        mapping = document.get("migrations", {})
        live = [task for task in live if not task.archived]
        with self._engine.begin() as db:
            held = self._active(db, name)
            if base is not _ANY and held != base:
                raise StaleBase(f"{name}: the active version is {held}, not the base {base}")
            if held == digest:
                if within is not None:
                    within(db)
                return digest
            _check_mapping(name, mapping, document["states"], live)
            _check_parents(name, document, self._documents(db))
            self._record(db, name, digest, document, held)
            for task in live:
                state = lane_id(task.state)
                if state in mapping and mapping[state] != state:
                    remap = NewEvent(
                        "Remapped",
                        {"mapping": {task.state: mapping[state]}},
                        "starpulse",
                        "registry",
                        definition_hash=digest,
                    )
                    self._store.append("task", task.id, task.version, [remap], connection=db)
                elif self._store.head_in(db, "task", task.id) != task.version:
                    raise StaleVersion(f"{task.id}: its stream moved after it was read at version {task.version}")
            if within is not None:
                within(db)
        return digest

    def active_hash(self, machine: str) -> str | None:
        """The hash of the version `machine`'s commands validate against, None before its first activation."""
        with self._engine.connect() as db:
            return self._active(db, machine)

    def active_definitions(self) -> dict[str, Mapping[str, Any]]:
        """The definition document each machine with an active version runs."""
        with self._engine.connect() as db:
            rows = db.execute(
                select(machine_active.c.machine, machine_versions.c.document)
                .join(machine_versions, machine_versions.c.hash == machine_active.c.hash)
                .order_by(machine_active.c.machine)
            )
            return {name: document for name, document in rows}

    def retire(self, machine: str) -> None:
        """Drop `machine`'s active version, keeping every version. Raises `MissingMachine` for a name with none, and
        `RefusedRetire` for the Board's machine or one an active machine lists as a submachine."""
        if machine == TASK_MACHINE:
            raise RefusedRetire(f"{machine}: the machine that moves Tasks cannot be retired")
        with self._engine.begin() as db:
            if self._active(db, machine) is None:
                raise MissingMachine(machine)
            parents = [name for name, document in self._documents(db).items() if machine in _submachines(document)]
            if parents:
                raise RefusedRetire(f"{machine}: still a submachine of {', '.join(sorted(parents))}")
            db.execute(delete(machine_active).where(machine_active.c.machine == machine))

    def definition(self, digest: str) -> Mapping[str, Any]:
        """The definition document that has `digest`."""
        with self._engine.connect() as db:
            found = db.execute(select(machine_versions.c.document).where(machine_versions.c.hash == digest)).scalar()
        if found is None:
            raise MachineDefinitionError(f"no definition has hash {digest}")
        return found

    def append(
        self,
        subject_kind: str,
        subject_id: str,
        expected_version: int,
        events: Sequence[NewEvent],
        *,
        machine: str = TASK_MACHINE,
    ) -> list[StoredEvent]:
        """`EventStore.append` of `events` stamped with the hash of `machine`'s active version, each State they name
        checked against it. Raises `MachineDefinitionError` when none is active or an Event names a State it lacks."""
        digest = self.active_hash(machine)
        if digest is None:
            raise MachineDefinitionError(f"{machine}: no definition is active")
        states = self.definition(digest)["states"]
        for event in events:
            named = event.payload.get(_STATE_FIELD.get(event.type, ""))
            if named is not None and lane_id(named) not in states:
                raise MachineDefinitionError(
                    f"{machine}: {event.type} names State {named}, which version {digest[:12]} lacks"
                )
        return self._store.append(
            subject_kind, subject_id, expected_version, [replace(e, definition_hash=digest) for e in events]
        )

    @staticmethod
    def _documents(db: Connection) -> dict[str, Mapping[str, Any]]:
        rows = db.execute(
            select(machine_active.c.machine, machine_versions.c.document).join(
                machine_versions, machine_versions.c.hash == machine_active.c.hash
            )
        )
        return {name: document for name, document in rows}

    @staticmethod
    def _active(db: Connection, machine: str) -> str | None:
        return active_version(db, machine)

    @staticmethod
    def _record(db: Connection, machine: str, digest: str, document: Mapping[str, Any], held: str | None) -> None:
        """Make `digest` active in place of `held`, the version the caller read: a write that finds another active raises
        `StaleBase`. It is the transaction's first write, so a SQLite store holds its write lock for what the caller checks next."""
        now = time.time()
        if db.execute(select(machine_versions.c.hash).where(machine_versions.c.hash == digest)).scalar() is None:
            db.execute(
                insert(machine_versions).values(hash=digest, machine=machine, document=dict(document), created_at=now)
            )
        try:
            if held is None:
                db.execute(insert(machine_active).values(machine=machine, hash=digest, activated_at=now))
                return
            moved = db.execute(
                update(machine_active)
                .where(machine_active.c.machine == machine, machine_active.c.hash == held)
                .values(hash=digest, activated_at=now)
            )
        except IntegrityError as error:
            raise StaleBase(f"{machine}: another version became active after {held} was read") from error
        if moved.rowcount != 1:
            raise StaleBase(f"{machine}: the active version is no longer {held}")


def _submachines(document: Mapping[str, Any]) -> set[str]:
    return {link.get("machine") for link in document.get("submachines", ())}


def _check_parents(machine: str, document: Mapping[str, Any], active: Mapping[str, Mapping[str, Any]]) -> None:
    """Refuse a document whose `parents` disagree with the active machines whose `submachines` name it. A declared parent
    with no active version yet is not held against it, so a first install may import a child before its parent."""
    declared = set(document.get("parents", ()))
    linked = {name for name, other in active.items() if name != machine and machine in _submachines(other)}
    absent = {name for name in declared if name in active and name != machine} - linked
    unnamed = linked - declared
    if absent or unnamed:
        raise MachineDefinitionError(
            f"{machine}: parents {sorted(declared)} disagree with the active machines whose submachines name it {sorted(linked)}"
        )


def _check_mapping(
    machine: str, mapping: Mapping[str, str], states: Mapping[str, Any], live: Sequence[LiveTask]
) -> None:
    """Refuse a mapping into a State the version lacks, then each dropped State a live Task holds that the mapping omits."""
    missing = [f"{old} -> {new}" for old, new in mapping.items() if new not in states]
    if missing:
        raise MachineDefinitionError(f"{machine}: migrations name States the version lacks: {', '.join(missing)}")
    stranded: dict[str, list[str]] = {}
    for task in live:
        state = lane_id(task.state)
        if state not in states and state not in mapping:
            stranded.setdefault(task.state, []).append(task.id)
    if stranded:
        held = "; ".join(f"{state} ({', '.join(ids)})" for state, ids in stranded.items())
        raise StrandedTasks(f"{machine}: States dropped with live Tasks and no migrations mapping: {held}")
