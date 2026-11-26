"""The machines the board draws: list them, read one's declared config, and write the store's."""

from collections.abc import Callable, Mapping
from typing import Any

from starpulse.board.adapters import policy_store
from starpulse.board.model.policy_diff import policy_of
from starpulse.contracts.api.dto.requests import MachineCreateRequest, MachineListRequest, MachinePutRequest
from starpulse.event_log.machine_store import MachineStore, MissingMachine, RefusedRetire
from starpulse.event_log.store import StaleVersion
from starpulse.event_log.store.machine_registry import StaleBase, StrandedTasks
from starpulse.machine_engine.model.machine_definition import MachineDefinitionError
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.views.application.commands.guard import lan_refusal, on_lan, with_request

_NO_STORE = (503, {"error": "this server keeps no machine store"})


@with_request(MachineListRequest, "Listing machines")
def machines_list(
    request: MachineListRequest, drawn: Mapping[str, dict], board_roles: Mapping[str, Any]
) -> tuple[int, dict[str, Any]]:
    """Every machine as the snapshot draws it (states, transitions, drawing) with its `type`, `parents` and `roles`,
    the Board's being `board_roles` and another's read off its states: the HTTP status and JSON body."""
    return 200, {
        "machines": [
            {"name": n, **m, "type": m.get("type"), "parents": m.get("parents", []), "roles": _roles(n, m, board_roles)}
            for n, m in drawn.items()
        ]
    }


def _roles(name: str, machine: Mapping[str, Any], board_roles: Mapping[str, Any]) -> Mapping[str, Any]:
    return board_roles if name == "board" else StateRoles.of_drawn(machine).wire()


def machine_record(
    drawn: Mapping[str, dict],
    name: str,
    lanes: Callable[[], dict[str, Any]] | None,
    store: MachineStore | None = None,
) -> tuple[int, dict[str, Any]]:
    """One machine's declared config: its `type`, `parents`, `skill` (the first parent link naming one), links and
    launches, and on the Board machine each lane's surface, with the `hash` of the version the store runs it under: the
    HTTP status and JSON body. A machine only the store holds is read from its stored definition."""
    digest = store.active_hash(name) if store else None
    stored = store.definition(digest) if digest else {}
    if not (machine := drawn.get(name) or stored):
        return 404, {"error": f"{name} is not a machine here"}
    parents = machine.get("parents", [])
    skill = next(
        (
            link["skill"]
            for parent in parents
            for link in drawn.get(parent, {}).get("submachines", ())
            if link["machine"] == name and link["skill"]
        ),
        "",
    )
    body = {
        "name": name,
        "type": machine.get("type"),
        "parents": parents,
        "skill": skill,
        "submachines": machine.get("submachines", []),
        "launches": machine.get("launches", {}) if name in drawn else {},
        "hash": digest,
    }
    return 200, body | {"lanes": lanes() if lanes else {}} if name == "board" else body


def _refusal(error: Exception) -> tuple[int, dict[str, str]]:
    """The status a refused machine write answers: 409 for a change the store's state refuses, 404 for a machine it lacks, 422 for a definition that does not compile."""
    if isinstance(error, MissingMachine):
        return 404, {"error": f"{error} is not a machine here"}
    if isinstance(error, StrandedTasks | StaleBase | RefusedRetire | StaleVersion):
        return 409, {"error": str(error)}
    return 422, {"error": str(error)}


@with_request(MachineCreateRequest, "Creating a machine")
def create_machine(request: MachineCreateRequest, store: MachineStore | None) -> tuple[int, dict[str, Any]]:
    """Add the machine `request` defines to the store: 201 with its `machine` and `hash`, 409 when the store has an
    active machine of the name, 422 for a definition that does not compile."""
    if store is None:
        return _NO_STORE
    try:
        digest = store.create(request.definition.document())
    except (MachineDefinitionError, StaleVersion) as error:
        return _refusal(error)
    return 201, {"machine": request.definition.name, "hash": digest}


@with_request(MachinePutRequest, "Changing a machine")
def put_machine(request: MachinePutRequest, name: str, store: MachineStore | None) -> tuple[int, dict[str, Any]]:
    """Make the definition `request` carries the version of `name` that follows `base`, with its `policy` rows written in
    the same transaction: 200 with `machine` and `hash`, 404 for a machine the store lacks, 409 for a stale `base` or a
    change that strands a live task, 422 for a definition that does not compile. A document or policy rows the request
    models refuse never reach here: 400."""
    if store is None:
        return _NO_STORE
    policy = None if request.policy is None else policy_of(request.policy.model_dump())
    within = None if policy is None else lambda db: policy_store.write(db, policy)
    try:
        digest = store.put(name, request.definition.document(), request.base, within)
    except (MachineDefinitionError, MissingMachine, StaleVersion) as error:
        return _refusal(error)
    return 200, {"machine": name, "hash": digest}


def delete_machine(source: str, name: str, store: MachineStore | None) -> tuple[int, dict[str, Any]]:
    """Retire `name`, keeping every version: 200 with `machine`, 404 for a machine with no active version, 409 for the
    Board's machine or one an active machine lists as a submachine."""
    if not on_lan(source):
        return lan_refusal("Retiring a machine")
    if store is None:
        return _NO_STORE
    try:
        store.retire(name)
    except (MachineDefinitionError, MissingMachine) as error:
        return _refusal(error)
    return 200, {"machine": name}
