"""The bodies a write route answers with when it succeeds."""

from __future__ import annotations

from starpulse.contracts.api._base import _Api


class Moved(_Api):
    task: str
    to: str
    advice: str | None = None


class Edited(_Api):
    task: str
    changed: list[str]


class Archived(_Api):
    task: str


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


class Reviewed(_Api):
    task: str
    to: str


class Created(_Api):
    task: str


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
