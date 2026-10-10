"""The `[[triggers]]` config tables: each declares a run to start when a board event arrives.

A table names the event stream it reads (`on`: `lane` for a task entering a lane, `machine` for a lifecycle-machine
event), the workflow to start (`start`, as `<instance>/<workflow>`) and optionally a `when` filter. `when` is the
machine guard's field match: each listed field of the event must match, by `equals`, `in` or `exists`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

__all__ = ["EVENTS", "Trigger", "TriggerError", "parse_triggers"]

#: The events a trigger may read.
EVENTS = ("lane", "machine")

_KEYS = {"on", "start", "when"}


@cache
def _validator() -> Any:
    """The machine schema's `when`, with its reserved field names lifted: those names collide with the state-machine
    library's injected arguments, which a guard's fields are passed as, but a trigger matches the entry's fields directly.

    Built on first use: `jsonschema` is the cost of importing this module, and a board read never parses a trigger.
    """
    from jsonschema import Draft202012Validator  # noqa: PLC0415 - import cost, paid on first use

    schema = json.loads((Path(__file__).parents[2] / "machine.schema.json").read_text())
    when = deepcopy(schema["$defs"]["when"])
    del when["propertyNames"]["not"]
    return Draft202012Validator({**when, "$defs": schema["$defs"]})


class TriggerError(ValueError):
    """A `[[triggers]]` table the view cannot run from; the message names the key to fix."""


@dataclass(frozen=True)
class Trigger:
    """One declared start: when an `on` event matches `when`, start the workflow `start` (`<instance>/<workflow>`)."""

    on: str
    start: str
    when: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def _trigger(raw: object, at: int) -> Trigger:
    who = f"triggers[{at}]"
    if not isinstance(raw, dict):
        raise TriggerError(f"{who} must be a [[triggers]] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise TriggerError(f"{who}: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    for key in ("on", "start"):
        if key not in raw:
            raise TriggerError(f"{who} needs {key}")
    on, start = raw["on"], raw["start"]
    if on not in EVENTS:
        raise TriggerError(f"{who}: on must be one of {', '.join(EVENTS)}")
    instance, _, workflow = start.partition("/") if isinstance(start, str) else ("", "", "")
    if not (instance and workflow):
        raise TriggerError(f"{who}: start must be <instance>/<workflow>")
    when = raw.get("when", {})
    if "when" in raw:
        from jsonschema.exceptions import best_match  # noqa: PLC0415 - import cost, paid on first use

        if (error := best_match(_validator().iter_errors(when))) is not None:
            where = "/".join(str(part) for part in error.absolute_path)
            raise TriggerError(f"{who}: when{f' {where}' if where else ''}: {error.message}")
    return Trigger(on, start, when)


def parse_triggers(raw: object) -> tuple[Trigger, ...]:
    """The `[[triggers]]` tables as triggers, or none for `None`; each refusal names the key to fix."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise TriggerError("triggers must be a list of [[triggers]] tables")
    return tuple(_trigger(table, at) for at, table in enumerate(raw))
