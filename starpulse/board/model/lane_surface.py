"""What a lane lets its holder call: the lane's allowed tools, its typed exit tools and the skill bound on entry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from starpulse.board.model.policy import Policy

__all__ = ["ExitTool", "LaneSurface", "lanes_of", "surface"]


@dataclass(frozen=True)
class ExitTool:
    name: str
    event: str
    #: The lane the event's route leads to.
    to: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class LaneSurface:
    tools: tuple[str, ...] = ()
    exits: tuple[ExitTool, ...] = ()
    skill: str | None = None


_NAMES = {
    "REVIEW": "board_review",
    "PARK_ON_CRITERIA": "board_park",
    "PARK_ON_TASK": "board_park",
    "DEFER": "board_defer",
    "FINALIZE": "board_finalize",
}
_TEXT = {"type": "string", "pattern": r"\S"}
_SCHEMAS: dict[str, dict[str, Any]] = {
    "board_park": {
        "reason": {**_TEXT, "description": "what is outstanding, recorded with the move"},
        "until": {
            "type": "string",
            "description": "TASK-<n> (or TASK-<n>#<criterion>) to wait for, else a condition a check can observe, as YAML or JSON",
        },
    },
    "board_defer": {"question": {**_TEXT, "description": "the question only the operator can answer"}},
}
_REQUIRED = {"board_park": ["reason"], "board_defer": ["question"]}


def surface(policy: Policy, lane: str) -> LaneSurface:
    """The tools the policy allows `lane`, an exit tool for each event an agent may fire from it, and its bound skill."""
    leaving: dict[str, str] = {}
    for route in policy.routes:
        if route.source == lane:
            leaving.setdefault(route.event, route.target)
    exits: dict[str, ExitTool] = {}
    for exit_ in policy.exits:
        if exit_.actor == "agent" and exit_.event in leaving:
            name = _NAMES.get(exit_.event, f"board_{exit_.event.lower()}")
            exits.setdefault(name, ExitTool(name, exit_.event, leaving[exit_.event], _schema(name)))
    skills = [row.skill for row in policy.lanes if row.name == lane]
    return LaneSurface(
        tools=tuple(tool.tool for tool in policy.tools if tool.lane == lane),
        exits=tuple(exits.values()),
        skill=skills[0] if skills else None,
    )


def lanes_of(policy: Policy) -> dict[str, dict[str, Any]]:
    """Each lane's surface as the JSON `/api/machines` serves, by lane name."""
    return {lane.name: asdict(surface(policy, lane.name)) for lane in policy.lanes}


def _schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": _SCHEMAS.get(name, {}),
        "additionalProperties": False,
    }
    if name in _REQUIRED:
        schema["required"] = _REQUIRED[name]
    return schema
