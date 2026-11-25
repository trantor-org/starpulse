"""The bodies a write route answers with when it succeeds."""

from typing import Literal

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.errors import ApiError, SkillRefusal


class Edited(_Api):
    """An edit's answer: `advice` is what the board tells the mover about the task now it is edited, when it has any;
    `warnings` are the lane rules an operator's move broke and landed."""

    task: str
    changed: list[str]
    advice: str = ""
    warnings: list[str] | None = None


class Archived(_Api):
    """A task archive's answer: `requested` when an agent's archive of an open task only recorded the request."""

    task: str
    requested: bool


class Restored(_Api):
    task: str


class TakenOver(_Api):
    task: str


class Retired(_Api):
    task: str


class Completed(_Api):
    task: str


class Reopened(_Api):
    task: str


class Dispatched(_Api):
    task: str
    session: str


class Parked(_Api):
    # `to` is the lane the task actor is asked to move the task to, not one the task is in
    task: str
    to: str


class FreezeRequested(_Api):
    # the task actor carries the request out, or answers it with a comment: the task is not yet frozen or unfrozen
    task: str
    request: Literal["freeze", "unfreeze"]


class Created(_Api):
    task: str


class CreatedEach(_Api):
    """A batch create's answer: each spec's new task, or why it was refused, in the order the specs came."""

    results: list[Created | SkillRefusal | ApiError]


class MilestoneCreated(_Api):
    milestone: str


class MilestoneEdited(_Api):
    milestone: str
    changed: list[str]


class MilestoneArchived(_Api):
    milestone: str


class MachineWritten(_Api):
    """`PUT /api/machines` and `PUT /api/machines/{name}`: the machine and the `hash` of the version now active."""

    machine: str
    hash: str


class MachineRetired(_Api):
    machine: str


class DocCreated(_Api):
    doc: str


class DocEdited(_Api):
    doc: str
    changed: list[str]


class DocArchived(_Api):
    doc: str


class Started(_Api):
    task: str
    url: str
    at: float


class Accepted(_Api):
    accepted: bool
    deprecated: str | None = None
