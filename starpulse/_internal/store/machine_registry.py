"""The machine registry: every compiled definition kept by its hash, one active per machine.

A command is validated against the active version and its Event records that version's hash, so a replay reads each
Event under the definition that wrote it. A change that drops a State holding live Tasks is accepted only with a
`migrations` mapping, and then every affected Task gets a `Remapped` Event in the same transaction that activates the
new version: one stale Task rolls the whole change back.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, insert, select, update

from starpulse._internal.machines.machine_definition import MachineDefinitionError, compile_document, validate
from starpulse._internal.machines.machine_namespace import definition_of
from starpulse._internal.store.event_store import EventStore, NewEvent, StoredEvent
from starpulse._internal.store.tables import machine_active, machine_versions

#: The machine that moves Tasks; the one a Task stream is validated and stamped under.
TASK_MACHINE = "board"
#: The payload field of each Event that names a State.
_STATE_FIELD = {"TaskCreated": "state", "TaskImported": "state", "Transitioned": "to"}


@dataclass(frozen=True)
class LiveTask:
    """A Task the change must carry across: its id, State and the stream head the caller read it at."""

    id: str
    state: str
    version: int


class MachineRegistry:
    def __init__(self, engine: Engine, store: EventStore) -> None:
        self._engine = engine
        self._store = store

    def activate(self, document: Mapping[str, Any], live: Sequence[LiveTask]) -> str:
        """Make `document` the active version of its machine and return its hash; a document that is already active
        changes nothing. Raises `MachineDefinitionError` naming the States and Tasks a missing mapping strands, and
        `StaleVersion` when a live Task moved since it was read; either leaves the active version as it was."""
        validate(document)
        name = document["name"]
        compile_document(dict(document), Path(name))
        digest = definition_of(document).digest
        mapping = document.get("migrations", {})
        with self._engine.begin() as db:
            if self._active(db, name) == digest:
                return digest
            _check_mapping(name, mapping, document["states"], live)
            for task in live:
                if task.state in mapping and mapping[task.state] != task.state:
                    remap = NewEvent(
                        "Remapped",
                        {"mapping": {task.state: mapping[task.state]}},
                        "starpulse",
                        "registry",
                        definition_hash=digest,
                    )
                    self._store.append("task", task.id, task.version, [remap], connection=db)
            self._record(db, name, digest, document)
        return digest

    def active_hash(self, machine: str) -> str | None:
        """The hash of the version `machine`'s commands validate against, None before its first activation."""
        with self._engine.connect() as db:
            return self._active(db, machine)

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
            if named is not None and named not in states:
                raise MachineDefinitionError(
                    f"{machine}: {event.type} names State {named}, which version {digest[:12]} lacks"
                )
        return self._store.append(
            subject_kind, subject_id, expected_version, [replace(e, definition_hash=digest) for e in events]
        )

    @staticmethod
    def _active(db: Connection, machine: str) -> str | None:
        return db.execute(select(machine_active.c.hash).where(machine_active.c.machine == machine)).scalar()

    @staticmethod
    def _record(db: Connection, machine: str, digest: str, document: Mapping[str, Any]) -> None:
        now = time.time()
        if db.execute(select(machine_versions.c.hash).where(machine_versions.c.hash == digest)).scalar() is None:
            db.execute(
                insert(machine_versions).values(hash=digest, machine=machine, document=dict(document), created_at=now)
            )
        if MachineRegistry._active(db, machine) is None:
            db.execute(insert(machine_active).values(machine=machine, hash=digest, activated_at=now))
        else:
            db.execute(
                update(machine_active).where(machine_active.c.machine == machine).values(hash=digest, activated_at=now)
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
        if task.state not in states and task.state not in mapping:
            stranded.setdefault(task.state, []).append(task.id)
    if stranded:
        held = "; ".join(f"{state} ({', '.join(ids)})" for state, ids in stranded.items())
        raise MachineDefinitionError(f"{machine}: States dropped with live Tasks and no migrations mapping: {held}")
