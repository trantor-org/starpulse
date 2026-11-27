"""A working task's phase, substate and flow, read from the machine rows it holds in a snapshot of the machines."""

from types import SimpleNamespace
from typing import Any


def board_flow(snapshot: dict[str, Any]) -> dict[str, Any]:
    return next(flow for flow in snapshot["flows"] if flow["name"] == "board")


def roles_of(snapshot: dict[str, Any]) -> SimpleNamespace:
    """The snapshot's state roles, each point an attribute: `roles_of(snapshot).done` is the State where work is done."""
    return SimpleNamespace(**snapshot["roles"])


def _newest(snapshot: dict[str, Any], flow: str, task: str) -> dict[str, Any] | None:
    """`task`'s newest row in machine `flow`, the earlier on a tie; None when the machine holds none."""
    machine = next((f for f in snapshot["flows"] if f["name"] == flow), None)
    rows = [a for a in machine["agents"] if a.get("task") == task] if machine else []
    return max(rows, key=lambda a: a.get("active") or 0, default=None)


def _holding(snapshot: dict[str, Any], links: list[dict[str, Any]], task: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The link among `links` whose submachine holds `task` in its newest row, and that row."""
    held = [(link, row) for link in links if (row := _newest(snapshot, link["machine"], task))]
    return max(held, key=lambda pair: pair[1].get("active") or 0, default=None)


def phase_of(agent: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """An In Progress task's `(phase, substate, flow)`, picked as the kanban card's `climb` does: the newest row among
    the submachines its In Progress row's state links, else among all the In Progress machine links, names the phase
    (that link's state), the substate (that row's state) and the flow. A task held by no submachine reads the In
    Progress row's state alone."""
    if agent["state"] != roles_of(snapshot).working:
        return None, None, None
    inner = board_flow(snapshot)["machine"].get("submachines") or [{}]
    machine = next((f for f in snapshot["flows"] if f["name"] == inner[0].get("machine")), None)
    if machine is None:
        return None, None, None
    row = _newest(snapshot, machine["name"], agent["id"])
    links = [link for link in machine["machine"].get("submachines", []) if link["machine"] != machine["name"]]
    held = _holding(snapshot, [link for link in links if row and link["state"] == row["state"]], agent["id"]) or _holding(snapshot, links, agent["id"])
    if held is None:
        return (row["state"], None, None) if row else (None, None, None)
    link, held_row = held
    return link["state"], held_row["state"], next(f for f in snapshot["flows"] if f["name"] == link["machine"])
