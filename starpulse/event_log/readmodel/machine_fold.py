"""The fold of one `machine:events` entry into its machine's task row: the machine's transition table decides the state,
and the trail keeps the task's latest steps. Only the Board child's projector calls it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from starpulse.contracts.adapters import MachineEvent, TaskKeys
from starpulse.machine_engine.model.transitions import tables

#: How many of a task's latest steps travel with it, so a page that connected after several steps can still walk each one.
TRAIL = 12
#: A machine a third party moves (`source`) keeps more: its history is the data the task view totals, not a recent-steps strip.
TRAIL_SOURCED = 120


def event_of(fields: Mapping[str, Any]) -> MachineEvent | None:
    """The machine event an entry's fields hold, or None for one that is not a machine event of the contract."""
    try:
        return MachineEvent.model_validate(dict(fields))
    except ValidationError:
        return None


class Placer:
    """Places a machine event on the task it moved, given the task's agent as the machine last placed it (None if none).

    With `keys`, an event whose task is not a key of that scheme places nothing; a run is no task key, so `keys` leaves it be.
    `drawn` are the machines the page draws; an event for any other machine places nothing.
    """

    def __init__(self, drawn: Mapping[str, dict], keys: TaskKeys | None = None) -> None:
        self._keys = keys
        self._tables = tables(drawn)
        self._sourced = {name: bool(machine.get("source")) for name, machine in drawn.items()}
        self._trail = {name: TRAIL_SOURCED if sourced else TRAIL for name, sourced in self._sourced.items()}

    def place(self, before: dict | None, event: MachineEvent) -> tuple[str, str, dict] | None:
        """The (machine, task, agent) the event leaves, or None when it places nothing."""
        flow, run = event.machine, event.run
        task = event.task or run
        table = self._tables.get(flow)
        if task is None or table is None or run is None and self._keys is not None and not self._keys.matches(task):
            return None
        state = table.target(before["state"] if before else None, event.event)
        if state is None:
            return None
        step = {"state": state, "event": event.event, "at": event.time} | ({"data": event.data} if event.data else {})
        if self._sourced[flow]:
            step["id"] = event.event_id  # a third party's step names its subject (a CI step, the pull request) for readers
        trail = [*(before["trail"] if before else []), step]
        agent = {
            "id": task,
            "title": task,
            "model": "",
            "task": task,
            "state": state,
            "steps": (before["steps"] if before else 0) + 1,
            "trail": trail[-self._trail[flow] :],
            "active": event.time,
        }
        return flow, task, agent
