"""The machines the page draws: states, transitions, writers and submachines."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.api._base import _Api


class MachineState(_Api):
    id: str
    name: str
    initial: bool
    final: bool
    role: str | None = Field(
        default=None,
        description="The type the machine declares the state: `initial`, `final`, `resting`, `waiting_on_fact` or "
        "`waiting_on_person`; null when it declares none.",
    )


class Cite(_Api):
    """The sentence of a skill that sends a session down a transition."""

    skill: str
    quote: str


class Transition(_Api):
    source: str
    target: str
    event: str
    cite: Cite | None = Field(
        default=None, description="The skill sentence that authorizes the transition; absent when its YAML cites none."
    )


class Writer(_Api):
    """Who fires a Board event: a runs workflow (by `<instance>/<workflow>` name), `operator` or `agent`."""

    actor: str
    trigger: str


class Submachine(_Api):
    """Where a Board state opens into another machine, and which Board event each inner final state fires."""

    state: str
    machine: str
    exits: dict[str, str]
    parent: str = Field(description="The machine the link opens under: `board`, or the machine whose `state` it hangs off.")
    when: str = Field(description="What has to hold for the inner machine to run under `state`; empty when always.")


class Launch(_Api):
    """A runs workflow's launch: the skill it starts and the machine that skill draws, null when it has none."""

    skill: str
    machine: str | None


class Machine(_Api):
    source: str | None = Field(
        default=None,
        description='The third party whose events move this machine ("GitHub"); absent for a machine StarPulse\'s own '
        "actors move.",
    )
    states: list[MachineState]
    transitions: list[Transition]
    submachines: list[Submachine] | None = Field(
        default=None,
        description="The machines that open under this machine's states; the board's first is its In Progress delivery "
        "machine.",
    )
    launches: dict[str, Launch] | None = Field(
        default=None, description="Only the board machine: the skill machine each launching DAG starts."
    )
    writers: dict[str, list[Writer]] | None = Field(default=None, description="Its YAML-declared writers per event.")
    dagActors: list[str] | None = Field(
        default=None, description="Only the board machine: the writers that are runs workflows."
    )
    mainLine: list[str] | None = Field(
        default=None, description="Only the board machine: the state ids along its axis, in order (New to Done)."
    )
    tiers: list[list[str]] | None = Field(
        default=None,
        description="Only the board machine: the state ids the Star Map draws at each stage, left to right, a tier's "
        "states stacked in its cell; a state no tier names is drawn with the tier at the mean of the tiers its "
        "transitions join it to, stacked in it or in a tier of its own after it, else in a tier of its own after the "
        "last, and with none the Board draws its own columns.",
    )
