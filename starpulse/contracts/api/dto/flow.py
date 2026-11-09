"""The workflows: settled tasks, ties and the flow snapshot."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.machine import Machine
from starpulse.contracts.api.dto.task import RawTask


class Settled(_Api):
    """A task that left the Board's lanes for good: where it settled, when, and the title, assignee, milestone and labels it settled with."""

    state: str
    at: float | None
    created: float | None
    title: str
    model: str
    milestone: str = Field(default="", description="The milestone it settled in; empty when it had none.")
    labels: list[str] = Field(default_factory=list, description="The labels it settled with.")


class Tie(_Api):
    """Where a lifecycle machine is entered from.

    `declared` is a Submachine on `machine`'s `state`; `observed` is the state the task held on `machine` when its session
    entered this one; `dag` is a launch by `dag`, which names no machine or state. `count` is the sessions entered
    through it, null for a launch.
    """

    kind: Literal["declared", "observed", "dag"]
    machine: str | None
    state: str | None
    count: int | None
    dag: str | None
    when: str = Field(description="What has to hold for a declared tie to run; empty otherwise.")


class Stuck(_Api):
    """The longest-stuck task of a machine and every machine nested below it: idle over two hours outside a final state."""

    machine: str
    state: str
    since: float = Field(description="When the task last moved, epoch seconds.")


class FlowSnapshot(_Api):
    name: str
    machine: Machine
    agents: list[RawTask]
    ties: list[Tie] | None = None
    parent: str | None = None
    depth: int | None = None
    chain: list[str] | None = None
    nested: list[str] | None = None
    last: float | None = None
    stuck: Stuck | None = None
