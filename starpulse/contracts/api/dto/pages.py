"""The paged and read routes of the done tasks and the machines."""

from typing import Any

from pydantic import Field

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.machine import Launch, Submachine
from starpulse.contracts.api.dto.task import RawTask


class DonePage(_Api):
    """`GET /api/done`: the next page of done tasks past their hot day, newest first, and whether older ones remain."""

    tasks: list[RawTask]
    more: bool


class ExitTool(_Api):
    """A typed exit tool of a lane: the event it fires and the JSON schema of its arguments."""

    name: str
    event: str
    to: str
    schema_: dict[str, Any] = Field(alias="schema")


class LaneSurface(_Api):
    """What a session holding the lane may call: its tools, its exit tools and the skill bound on entry."""

    tools: list[str]
    exits: list[ExitTool]
    skill: str | None


class MachineListed(_Api):
    """A machine of `POST /api/machines`: its name, its `type` and the machines it is a submachine of."""

    name: str
    type: str | None
    parents: list[str]


class Machines(_Api):
    """`POST /api/machines`: every machine the board draws."""

    machines: list[MachineListed]


class MachineDetail(_Api):
    """`GET /api/machines/{name}`: one machine's declared config. `skill` is the one its first parent link runs it with
    (empty when none names one); `lanes` is each lane's surface by lane name, on the Board machine only; `hash` is the
    version the store runs it under, the `base` of a write, and absent when the store holds none."""

    name: str
    type: str | None
    parents: list[str]
    skill: str
    submachines: list[Submachine]
    launches: dict[str, Launch]
    lanes: dict[str, LaneSurface] | None = None
    hash: str | None = None
