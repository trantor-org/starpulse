"""The machines the board draws: list them and read one's declared config."""

from collections.abc import Callable, Mapping
from typing import Any

from starpulse.contracts.api.dto.requests import MachineListRequest
from starpulse.views.application.commands.guard import with_request


@with_request(MachineListRequest, "Listing machines")
def machines_list(request: MachineListRequest, drawn: Mapping[str, dict]) -> tuple[int, dict[str, Any]]:
    """Every machine with its `type` and `parents`: the HTTP status and JSON body."""
    return 200, {"machines": [{"name": n, "type": m.get("type"), "parents": m.get("parents", [])} for n, m in drawn.items()]}


def machine_record(
    drawn: Mapping[str, dict], name: str, lanes: Callable[[], dict[str, Any]] | None
) -> tuple[int, dict[str, Any]]:
    """One machine's declared config: its `type`, `parents`, `skill` (the first parent link naming one), links and
    launches, and on the Board machine each lane's surface: the HTTP status and JSON body."""
    if (machine := drawn.get(name)) is None:
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
        "launches": machine.get("launches", {}),
    }
    return 200, body | {"lanes": lanes() if lanes else {}} if name == "board" else body
