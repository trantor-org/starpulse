"""A Board task as a verb or a held-task stream reports it, read from a snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from starpulse.contracts.adapters import Move

#: Who `task move` moves as: the machine YAML's writers say which moves an agent may make.
AGENT = "agent"


def board_flow(snapshot: dict[str, Any]) -> dict[str, Any]:
    return next(flow for flow in snapshot["flows"] if flow["name"] == "board")


def _agent_moves(agent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The verdict on each column as the agent meets it: a move the board machine leaves to others is refused."""
    return {
        column: Move.model_validate(raw).for_actor(AGENT).model_dump(include={"allowed", "reason", "skill"})
        for column, raw in agent["moves"].items()
    }


def roles_of(snapshot: dict[str, Any]) -> SimpleNamespace:
    """The snapshot's state roles, each point an attribute: `roles_of(snapshot).done` is the State where work is done."""
    return SimpleNamespace(**snapshot["roles"])


def done_ids(snapshot: dict[str, Any]) -> set[str]:
    """The tasks a dependency no longer waits on: those in the done lane, those past their hot day (`cold_done`, held
    by the full view alone) and those settled as completed."""
    done = {task["id"] for task in board_flow(snapshot)["agents"] if task["state"] == roles_of(snapshot).done}
    done |= set(snapshot.get("cold_done", ()))
    return done | {task_id for task_id, entry in snapshot["settled"].items() if entry["state"] == "completed"}


def cold_agent(task_id: str, record: dict[str, Any], done: str) -> dict[str, Any]:
    """A cold done task as a snapshot agent, built from its board record (`GET /api/task`) for a verb to view whole."""
    return {
        "id": task_id,
        "title": record["title"],
        "state": done,
        "model": record["profile"],
        "profile": record["profile"],
        "milestone": record["milestone"],
        "type": record["type"],
        "labels": record["labels"],
        "dependencies": record["dependencies"],
        "criteria": [{"text": item["text"], "checked": item["checked"]} for item in record["acceptanceCriteria"]],
        "prs": [],
        "moves": {},
        "description": record["description"],
    }


def _state_in(snapshot: dict[str, Any], flow: str, task: str) -> str | None:
    """The state `task` is in within machine `flow`, None when the machine holds no such task."""
    machine = next((f for f in snapshot["flows"] if f["name"] == flow), None)
    return next((a["state"] for a in machine["agents"] if a.get("task") == task), None) if machine else None


def _holding(snapshot: dict[str, Any], links: list[dict[str, Any]], task: str) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
    """The first of `links`' submachines that holds `task`: its link, the state `task` holds in it, and its flow."""
    for link in links:
        flow = next((f for f in snapshot["flows"] if f["name"] == link["machine"]), None)
        if flow and (state := _state_in(snapshot, link["machine"], task)):
            return link, state, flow
    return None


def _phase(agent: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """An In Progress task's `(phase, substate, flow)`: the state of the In Progress machine, the state of the first
    submachine that phase links which holds the task, and that submachine's flow. Only the current phase's submachines
    count."""
    if agent["state"] != roles_of(snapshot).working:
        return None, None, None
    inner = board_flow(snapshot)["machine"].get("submachines") or [{}]
    machine = next((f for f in snapshot["flows"] if f["name"] == inner[0].get("machine")), None)
    if machine is None:
        return None, None, None
    phase = _state_in(snapshot, machine["name"], agent["id"])
    links = machine["machine"].get("submachines", [])
    if phase is None:
        # the subflows hold the task while the In Progress machine has no state for it: the first to hold it names the phase
        held = _holding(snapshot, links, agent["id"])
        return (None, None, None) if held is None else (held[0]["state"], held[1], held[2])
    held = _holding(snapshot, [link for link in links if link["state"] == phase], agent["id"])
    return (phase, None, None) if held is None else (phase, held[1], held[2])


def _skill(substate: str | None, flow: dict[str, Any] | None) -> dict[str, Any] | None:
    """The skill a held task is in: its machine's states in order, the state it holds, and the next edge its machine declares."""
    if flow is None:
        return None
    return {
        "name": flow["name"],
        "states": [state["id"] for state in flow["machine"]["states"]],
        "current": substate,
        "next": flow["machine"].get("next"),
    }


def task_view(agent: dict[str, Any], snapshot: dict[str, Any], done: set[str] | None = None) -> dict[str, Any]:
    """A Board task as a verb reports it. It waits on each dependency not in `done`, read from `snapshot` when absent:
    a caller viewing many tasks passes it once rather than rescanning the board per task."""
    pulls = {pull["url"]: pull for pull in snapshot["pulls"].get(agent["id"], [])}
    if done is None:
        done = done_ids(snapshot)
    phase, substate, flow = _phase(agent, snapshot)
    entered = agent.get("entered")
    return {
        "id": agent["id"],
        "title": agent["title"],
        "lane": agent["state"],
        "phase": phase,
        "substate": substate,
        "skill": _skill(substate, flow),
        "interactive": snapshot.get("interactive", {}).get(agent["id"], False),
        "done_at": datetime.fromtimestamp(entered, UTC).isoformat() if agent["state"] == roles_of(snapshot).done and entered else None,
        "profile": agent["model"],
        "assignee": agent.get("assignee", ""),
        "milestone": agent["milestone"],
        "type": agent.get("type", ""),
        "labels": agent["labels"],
        "dependencies": agent["dependencies"],
        "waiting_on": [dependency for dependency in agent["dependencies"] if dependency not in done],
        "criteria": agent.get("criteria", []),
        "pause_reason": agent.get("pause_reason", ""),
        "prs": [pulls.get(url, {"url": url}) for url in agent["prs"]],
        "moves": _agent_moves(agent),
        "rating": snapshot.get("ratings", {}).get(agent["id"]),
        "released": agent.get("released"),
    }


def board_columns(
    snapshot: dict[str, Any], kept: Callable[[dict[str, Any]], bool], state: str | None = None
) -> dict[str, Any]:
    """Each Board column, or only `state`'s, with the tasks in it that `kept` keeps."""
    board = board_flow(snapshot)
    done = done_ids(snapshot)
    return {
        "columns": [
            {
                "state": column["id"],
                "name": column["name"],
                "tasks": [
                    task_view(a, snapshot, done) for a in board["agents"] if a["state"] == column["id"] and kept(a)
                ],
            }
            for column in board["machine"]["states"]
            if not state or column["id"] == state
        ]
    }
