"""A Board task as a verb or a held-task stream reports it, read from a snapshot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starpulse._internal.feed.board_feed import DONE
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


def task_view(agent: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """A Board task as a verb reports it. It waits on each dependency neither completed nor in the `done` lane."""
    pulls = {pull["url"]: pull for pull in snapshot["pulls"].get(agent["id"], [])}
    done = {task["id"] for task in board_flow(snapshot)["agents"] if task["state"] == DONE}
    done |= {task_id for task_id, entry in snapshot["settled"].items() if entry["state"] == "completed"}
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
    return {
        "columns": [
            {
                "state": column["id"],
                "name": column["name"],
                "tasks": [task_view(a, snapshot) for a in board["agents"] if a["state"] == column["id"] and kept(a)],
            }
            for column in board["machine"]["states"]
            if not state or column["id"] == state
        ]
    }
