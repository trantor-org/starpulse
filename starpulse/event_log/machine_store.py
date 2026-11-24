"""The machines the store holds, written through the API: create, upsert over a base and retire.

Every version stays in `starpulse_machine_versions`; a retired machine only loses its active row. A machine the store
has a version of is never imported from its file again, so a start-up sync cannot undo a write made here.
"""

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Connection, Engine

from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store.event_store import EventStore
from starpulse.event_log.store.machine_registry import (
    TASK_MACHINE,
    LiveTask,
    MachineRegistry,
    MissingMachine,
    RefusedRetire,
)
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError

__all__ = ["MachineStore", "MissingMachine", "RefusedRetire"]

_EVERY_TASK = 2**31 - 1


class MachineStore:
    def __init__(self, engine: Engine, store: EventStore | None = None) -> None:
        self._engine = engine
        self._store = store or EventStore(engine)
        self.registry = MachineRegistry(engine, self._store)

    def active_hash(self, name: str) -> str | None:
        return self.registry.active_hash(name)

    def definition(self, digest: str) -> Mapping[str, Any]:
        return self.registry.definition(digest)

    def imported(self, name: str) -> bool:
        return self.registry.imported(name)

    def create(self, document: Mapping[str, Any]) -> str:
        """Activate `document` as a machine the store has no active version of; `StaleBase` when the name is taken."""
        return self.registry.activate(document, self._live(document.get("name")), base=None)

    def put(
        self,
        name: str,
        document: Mapping[str, Any],
        base: str,
        within: Callable[[Connection], None] | None = None,
    ) -> str:
        """Activate `document` over the version `base` names, with `within` run in the same transaction. Raises
        `MissingMachine` for a name with no active version, `StaleBase` and `StrandedTasks` as `activate` does."""
        if document.get("name") != name:
            raise MachineDefinitionError(f"{name}: the definition is named {document.get('name')}")
        if self.active_hash(name) is None:
            raise MissingMachine(name)
        return self.registry.activate(document, self._live(name), base=base, within=within)

    def retire(self, name: str) -> None:
        self.registry.retire(name)

    def _live(self, name: object) -> list[LiveTask]:
        """The Tasks a change to `name` must carry across: the Board machine's, none for any other."""
        return self.live_tasks() if name == TASK_MACHINE else []

    def live_tasks(self) -> list[LiveTask]:
        """Every Task with a State, archived ones included (a Task that only ever archived has none to carry)."""
        Projector(self._engine, self._store).catch_up()
        rows = ReadModel(self._engine).since(0, _EVERY_TASK)
        return [LiveTask(row["id"], row["state"], row["version"], row["archived"]) for row in rows if row["state"]]
