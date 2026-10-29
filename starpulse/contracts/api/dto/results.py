"""The bodies a write route answers with when it succeeds."""

from __future__ import annotations

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.errors import ApiError, SkillRefusal


class Moved(_Api):
    """A move's answer. The operator's move of an unheld task into the working state also starts its session: `url`
    opens it, or `startError` says why none started."""

    task: str
    to: str
    advice: str | None = None
    url: str | None = None
    startError: str | None = None


class MovedEach(_Api):
    """A batch move's answer: the tasks it moved, and each refused task with why."""

    moved: list[str]
    refused: dict[str, str]


class Edited(_Api):
    task: str
    changed: list[str]


class Archived(_Api):
    task: str


class ArchivedEach(_Api):
    """A batch archive's answer: the tasks it archived, and each refused task with why."""

    archived: list[str]
    refused: dict[str, str]


class Judged(_Api):
    task: str
    check: str
    verdict: str
    fix: str | None = None


class Rated(_Api):
    task: str
    verdict: str
    reason: str
    changes: int


class Restored(_Api):
    task: str


class TakenOver(_Api):
    task: str


class Retired(_Api):
    task: str


class RetiredImported(_Api):
    task: str


class Completed(_Api):
    task: str


class Claimed(_Api):
    task: str
    to: str
    assignee: str


class Parked(_Api):
    task: str
    to: str


class Answered(_Api):
    task: str
    id: str


class Reviewed(_Api):
    task: str
    to: str


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


class DocCreated(_Api):
    doc: str


class DocEdited(_Api):
    doc: str
    changed: list[str]


class DocArchived(_Api):
    doc: str


class DocRestored(_Api):
    doc: str


class Started(_Api):
    task: str
    url: str
    at: float


class RunStarted(_Api):
    runId: str


class Accepted(_Api):
    accepted: bool
    deprecated: str | None = None
