"""A machine as plain data, and the run of one through events.

A `Machine` subclass carries the `states` a definition declares. An instance sits in one state and takes the first
transition of an event whose `when` field matches (`equals`, `in`, `exists`) hold for the facts sent with it; an
event the state cannot take is ignored. A taken transition tells the machine's model, when it defines them:
`on_transition(event)` and `on_<EVENT>()`.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

__all__ = ["Machine", "State", "Transition", "field_matches", "machine_class"]


class State:
    """A declared state and the transitions that leave it, in declaration order."""

    def __init__(self, id: str, *, initial: bool = False, final: bool = False) -> None:
        self.id = id
        self.name = id.replace("_", " ").capitalize()
        self.initial = initial
        self.final = final
        self.transitions: list[Transition] = []


@dataclass(frozen=True)
class Transition:
    """One event's move from `source` to `target`, taken when `when` holds and `unless` does not."""

    source: State
    target: State
    event: str
    when: Mapping[str, Mapping[str, Any]] | None = None
    unless: Mapping[str, Mapping[str, Any]] | None = None

    def allows(self, facts: Mapping[str, Any]) -> bool:
        return (self.when is None or field_matches(self.when, facts)) and (
            self.unless is None or not field_matches(self.unless, facts)
        )


def field_matches(when: Mapping[str, Mapping[str, Any]], fields: Mapping[str, Any]) -> bool:
    """Whether every field `when` lists matches `fields`: the grammar a guard's `when:` uses."""
    return all(_holds(match, name in fields, fields.get(name)) for name, match in when.items())


def _holds(match: Mapping[str, Any], present: bool, value: Any) -> bool:
    if "exists" in match:
        return present == match["exists"]
    if not present:
        return False
    return value == match["equals"] if "equals" in match else value in match["in"]


class Machine:
    """A machine's declaration as class attributes, and an instance that moves through it.

    `model` holds the extended state a machine's callbacks change; `start_value` is the id of the state it begins in
    when that is not the initial one. `RESTS` names states a procedure ends in though an event leaves them."""

    states: tuple[State, ...] = ()
    states_map: Mapping[str, State] = {}
    RESTS: Collection[str] = ()
    writers: Mapping[str, Any] = {}
    citations: Mapping[tuple[str, str, str], Mapping[str, str]] = {}
    source: str | None = None
    roles: Mapping[str, str | None] = {}
    priorities: Mapping[str, int] = {}

    def __init__(self, model: Any = None, start_value: str | None = None) -> None:
        self.model = SimpleNamespace() if model is None else model
        self.current_state_value = start_value or next(state.id for state in self.states if state.initial)

    @property
    def configuration(self) -> frozenset[State]:
        """The state the machine is in, as a set: the shape the paths and conformance code read."""
        return frozenset({self.states_map[self.current_state_value]})

    @property
    def is_terminated(self) -> bool:
        return self.states_map[self.current_state_value].final

    def enabled_events(self, **facts: Any) -> list[str]:
        """The events the current state takes for `facts`, in declaration order."""
        return list(
            dict.fromkeys(t.event for t in self.states_map[self.current_state_value].transitions if t.allows(facts))
        )

    def send(self, event: str, **facts: Any) -> None:
        """Take `event`'s first transition that `facts` allow; an event the state cannot take changes nothing."""
        for transition in self.states_map[self.current_state_value].transitions:
            if transition.event == event and transition.allows(facts):
                self.current_state_value = transition.target.id
                for name, args in (("on_transition", (event,)), (f"on_{event}", ())):
                    if callback := getattr(self.model, name, None):
                        callback(*args)
                return


def machine_class(name: str, states: Sequence[State]) -> type[Machine]:
    """The `Machine` subclass `name` that declares `states`."""
    return type(name, (Machine,), {"states": tuple(states), "states_map": {state.id: state for state in states}})
