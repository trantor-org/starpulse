"""A Board task as a verb or a held-task stream reports it, read from a snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from starpulse._internal.machines.transitions import DONE
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


def done_ids(snapshot: dict[str, Any]) -> set[str]:
    """The tasks a dependency no longer waits on: those in the `done` lane, those past their hot day (`cold_done`, held
    by the full view alone) and those settled as completed."""
    done = {task["id"] for task in board_flow(snapshot)["agents"] if task["state"] == DONE}
    done |= set(snapshot.get("cold_done", ()))
    return done | {task_id for task_id, entry in snapshot["settled"].items() if entry["state"] == "completed"}


def cold_agent(task_id: str, record: dict[str, Any]) -> dict[str, Any]:
    """A cold done task as a snapshot agent, built from its board record (`GET /api/task`) for a verb to view whole."""
    return {
        "id": task_id,
        "title": record["title"],
        "state": DONE,
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


def _phase(agent: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str | None, str | None]:
    """An In Progress task's `(phase, substate)`: the state of the In Progress machine, and the state of the first
    subflow that phase links which holds the task. Only the current phase's subflows count."""
    if agent["state"] != "in_progress":
        return None, None
    inner = board_flow(snapshot)["machine"].get("subflows") or [{}]
    machine = next((f for f in snapshot["flows"] if f["name"] == inner[0].get("flow")), None)
    if machine is None:
        return None, None
    phase = _state_in(snapshot, machine["name"], agent["id"])
    states = (_state_in(snapshot, link["flow"], agent["id"]) for link in machine["machine"].get("subflows", []) if link["state"] == phase)
    return phase, next((state for state in states if state), None)


def task_view(agent: dict[str, Any], snapshot: dict[str, Any], done: set[str] | None = None) -> dict[str, Any]:
    """A Board task as a verb reports it. It waits on each dependency not in `done`, read from `snapshot` when absent:
    a caller viewing many tasks passes it once rather than rescanning the board per task."""
    pulls = {pull["url"]: pull for pull in snapshot["pulls"].get(agent["id"], [])}
    if done is None:
        done = done_ids(snapshot)
    phase, substate = _phase(agent, snapshot)
    entered = agent.get("entered")
    return {
        "id": agent["id"],
        "title": agent["title"],
        "lane": agent["state"],
        "phase": phase,
        "substate": substate,
        "done_at": datetime.fromtimestamp(entered, UTC).isoformat() if agent["state"] == DONE and entered else None,
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
