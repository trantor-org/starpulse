"""Where a lifecycle's points are, read from the roles a machine declares and never from a State's name."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:
    from starpulse.machine_engine.model.machine_definition import Compiled

__all__ = ["StateRoles"]

#: The fact kind each point of the task lifecycle waits on: Start Criteria not yet met, met, and a pull request's end.
_UNMET, _MET, _PULL_REQUEST = "criteria_unmet", "criteria_met", "pr_terminal"


@dataclass(frozen=True)
class StateRoles:
    """The States of one machine by role, in the order the machine lists them.

    A State is told apart by what it does: `waits` names the facts it waits on, `rests` the resting States where a
    lifecycle ends without being final.
    """

    roles: Mapping[str, str | None]
    waits: Mapping[str, Mapping[str, str]]
    rests: Sequence[str] = ()

    @classmethod
    def of_machine(cls, compiled: Compiled) -> StateRoles:
        """The roles `compiled` declares."""
        return cls(compiled.roles, compiled.waits, tuple(compiled.drawing.get("rests", ())))

    @classmethod
    def of_statuses(cls, statuses: Sequence[str]) -> StateRoles:
        """The roles of a board that only lists statuses: the first is initial, the last final, the rest resting."""
        ids = [lane_id(status) for status in statuses]
        last = len(ids) - 1
        return cls({s: "initial" if i == 0 else "final" if i == last else "resting" for i, s in enumerate(ids)}, {})

    @classmethod
    def of_drawn(cls, machine: Mapping[str, Any]) -> StateRoles:
        """The roles of a drawn machine, which marks only its initial and final States."""
        states = machine["states"]
        return cls({s["id"]: "initial" if s.get("initial") else "final" if s.get("final") else None for s in states}, {})

    def wire(self) -> dict[str, str | list[str] | None]:
        """The roles as the snapshot sends them, for a client that holds no machine to read them from."""
        points = ("initial", "final", "done", "working", "ready", "waiting", "review", "attention")
        return {**{point: getattr(self, point) for point in points}, "startable": sorted(self.startable)}

    def _first(self, role: str) -> str | None:
        return next((state for state, declared in self.roles.items() if declared == role), None)

    def _waiting_on(self, fact: str) -> str | None:
        return next((state for state, facts in self.waits.items() if fact in facts), None)

    @property
    def initial(self) -> str | None:
        """Where a task starts."""
        return self._first("initial")

    @property
    def final(self) -> str | None:
        """Where a task is settled for good."""
        return self._first("final")

    @property
    def done(self) -> str | None:
        """Where the work is done: the resting State `rests` names, else the final one."""
        return self.rests[0] if self.rests else self.final

    @property
    def working(self) -> str | None:
        """Where a session works a task: the first resting State that is not where the lifecycle ends."""
        return next(
            (state for state, role in self.roles.items() if role == "resting" and state not in self.rests), None
        )

    @property
    def ready(self) -> str | None:
        """Where a task waits to be picked up: the State that waits for its Start Criteria to turn unmet."""
        return self._waiting_on(_UNMET)

    @property
    def waiting(self) -> str | None:
        """Where a task waits on its Start Criteria or dependencies: the State that waits for them to be met."""
        return self._waiting_on(_MET)

    @property
    def review(self) -> str | None:
        """Where a task waits on its pull request."""
        return self._waiting_on(_PULL_REQUEST)

    @property
    def attention(self) -> str | None:
        """Where a task waits on a person."""
        return self._first("waiting_on_person")

    @property
    def startable(self) -> frozenset[str]:
        """The States a session starts a task from: those waiting on a person or on a fact other than a pull request."""
        waiting = {"waiting_on_fact", "waiting_on_person"}
        return frozenset(
            state for state, role in self.roles.items() if role in waiting and _PULL_REQUEST not in self.waits.get(state, {})
        )
