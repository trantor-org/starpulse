"""The paged and read routes of the done tasks and the machines."""

from typing import Any

from pydantic import Field

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.machine import Launch, Machine, Submachine
from starpulse.contracts.api.dto.snapshot import Roles
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


class MachineListed(Machine):
    """A machine of `POST /api/machines`: the machine as the snapshot draws it, with its name, its `type`, the
    machines it is a submachine of and the `roles` of its states."""

    name: str
    type: str | None
    parents: list[str]
    roles: Roles


class Machines(_Api):
    """`POST /api/machines`: every machine the board draws."""

    machines: list[MachineListed]


class DailyReportItem(_Api):
    """One bucket of a daily report: the transitions counted and the summed length of the Stays they ended."""

    bucket: str
    count: int
    seconds: float


class DailyReports(_Api):
    """`POST /api/daily-reports`: the buckets of one machine's range, empty when it made no move in it."""

    items: list[DailyReportItem]


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
