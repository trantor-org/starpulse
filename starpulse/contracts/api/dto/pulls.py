"""The pull records `/api/pulls` lists."""

from __future__ import annotations

from typing import Literal

from starpulse.contracts.api._base import _Api


class RequiredCheck(_Api):
    name: str
    result: Literal["pass", "failing", "pending"]


class PullThread(_Api):
    """An unresolved review thread: its id and the login of its first comment's author, null for a deleted account."""

    id: str
    author: str | None


class PullRecord(_Api):
    """One pull request the PR store read from GitHub, as of `fetchedAt` (epoch seconds).

    `headRefName` and `unresolvedThreads` (the first 100 threads) are null for a record saved before they were kept."""

    repo: str
    number: int
    state: Literal["OPEN", "MERGED", "CLOSED"]
    isDraft: bool
    mergeable: str
    baseRefName: str
    headRefOid: str
    body: str
    checks: Literal["pass", "failing", "pending", "none"]
    requiredChecks: list[RequiredCheck]
    threads: int
    unresolvedThreads: list[PullThread] | None
    headRefName: str | None
    updatedAt: str
    mergedAt: str | None
    mergeSha: str | None
    fetchedAt: float


class Pulls(_Api):
    """`GET /api/pulls`: the stored pull requests matching every filter given, by repository then number."""

    pulls: list[PullRecord]
