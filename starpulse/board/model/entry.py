"""A lane's entry effects: what entering a lane does to a task, whichever writer moves it.

`[[board.entry]]` lists them. Each is `{lane, set}`: `lane` is the state whose entry fires it and `set` a table of front
matter fields to fill when the task holds none. `profile` is its one field, `{matrix = true}` the profile the board's
`default_profiles` give the task's `kind-*` and `size-*` labels (nothing when it lacks either, and the lane's rules then
judge the task as it is).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from starpulse.machine_engine.model.transitions import lane_id

__all__ = ["Effect", "default_profile", "entered", "load"]

_ENTRY_KEYS = {"lane", "set"}
#: The one field a matrix value fills, kept as the one-item list a profile edit stores.
_PROFILE = "profile"


def default_profile(labels: Sequence[str], defaults: Mapping[str, Mapping[str, str]]) -> str | None:
    """The board's default profile for the `kind-*` and `size-*` labels, None when the labels or the defaults lack them."""
    kinds = [label.removeprefix("kind-") for label in labels if label.startswith("kind-")]
    sizes = [label.removeprefix("size-") for label in labels if label.startswith("size-")]
    return defaults.get(kinds[0], {}).get(sizes[0]) if len(kinds) == 1 and len(sizes) == 1 else None


@dataclass(frozen=True)
class Effect:
    """On entering `lane`, a task with no `field` gets what `fill` returns for its front matter, when it returns any."""

    lane: str
    field: str
    fill: Callable[[Mapping[str, Any]], object | None]


def _matrix(defaults: Mapping[str, Mapping[str, str]]) -> Callable[[Mapping[str, Any]], object | None]:
    def fill(front: Mapping[str, Any]) -> object | None:
        profile = default_profile([str(label) for label in front.get("labels") or ()], defaults)
        return [profile] if profile else None

    return fill


def load(declared: object, defaults: Mapping[str, Mapping[str, str]]) -> tuple[Effect, ...]:
    """The effects a `[board] entry` setting declares, in order; one the board cannot read is a ValueError naming it."""
    if declared is None:
        return ()
    if not isinstance(declared, list):
        raise ValueError("board: entry must be a list of tables, `[[board.entry]]`")
    effects = []
    for number, spec in enumerate(declared):
        where = f"board: entry[{number}]"
        if not isinstance(spec, dict) or spec.keys() != _ENTRY_KEYS:
            raise ValueError(f"{where}: an effect is a table with `lane` and `set`")
        lane, fields = spec["lane"], spec["set"]
        if not isinstance(lane, str) or not lane.strip():
            raise ValueError(f"{where}: `lane` is a state name")
        if not isinstance(fields, dict) or not fields:
            raise ValueError(f"{where}: `set` is a table of fields to fill")
        for field, value in fields.items():
            if field != _PROFILE:
                raise ValueError(f"{where}: an entry fills `{_PROFILE}`, not `{field}`")
            if value != {"matrix": True}:
                raise ValueError(f"{where}: {field} takes `{{matrix = true}}`")
            effects.append(Effect(lane_id(lane.strip()), _PROFILE, _matrix(defaults)))
    return tuple(effects)


def entered(effects: Sequence[Effect], front: Mapping[str, Any], earlier: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """`front` with the fields the effects of the lane it now holds fill, when the write moved the task into it from
    `earlier` (None for a create); `front` itself when it fills none."""
    lane = lane_id(str(front.get("status") or ""))
    if earlier is not None and lane_id(str(earlier.get("status") or "")) == lane:
        return front
    filled = dict(front)
    for effect in effects:
        if effect.lane == lane and not filled.get(effect.field):
            value = effect.fill(filled)
            if value is not None:
                filled[effect.field] = value
    return front if filled == front else filled
