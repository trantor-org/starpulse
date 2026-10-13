"""A Board task as a verb or a held-task stream reports it, read from a snapshot."""

from __future__ import annotations

from collections.abc import Callable
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
    """The tasks a dependency no longer waits on: those in the `done` lane and those settled as completed."""
    done = {task["id"] for task in board_flow(snapshot)["agents"] if task["state"] == DONE}
    return done | {task_id for task_id, entry in snapshot["settled"].items() if entry["state"] == "completed"}


def task_view(agent: dict[str, Any], snapshot: dict[str, Any], done: set[str] | None = None) -> dict[str, Any]:
    """A Board task as a verb reports it. It waits on each dependency not in `done`, read from `snapshot` when absent:
    a caller viewing many tasks passes it once rather than rescanning the board per task."""
    pulls = {pull["url"]: pull for pull in snapshot["pulls"].get(agent["id"], [])}
    if done is None:
        done = done_ids(snapshot)
    return {
        "id": agent["id"],
        "title": agent["title"],
        "lane": agent["state"],
        "assignee": agent["model"],
        "holder": agent.get("holder", ""),
        "milestone": agent["milestone"],
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
