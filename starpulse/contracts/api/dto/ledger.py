"""The ledgers: runs, resolutions, failures and their strips."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from starpulse.contracts.adapters import RunStatus
from starpulse.contracts.api._base import _Api


class LedgerRun(_Api):
    """One DAG run a merge row carries: `inferred` when time, not the commit, paired it, and `ambiguous` how many other merges landed in its window."""

    runId: str
    status: RunStatus
    raw: str | None = None
    startedAt: str
    finishedAt: str
    steps: dict[str, RunStatus]
    step: str = Field(description='The step running now, or "".')
    inferred: bool
    ambiguous: int


class LedgerResolved(_Api):
    runId: str
    at: str


class LedgerFail(_Api):
    """A failed run of a cue the merge row holds open: the step it stopped at, and how the failure clears."""

    runId: str
    step: str
    startedAt: str
    finishedAt: str
    resolves: Literal["forced", "next"] | None
    resolved: LedgerResolved | None


class LedgerPull(_Api):
    repo: str
    number: int
    url: str


class LedgerRow(_Api):
    """One merge occurrence: its pull request and commit, the runs paired with it by DAG, and, for another repository's
    merge, the parent merge that pinned it."""

    key: str
    at: float = Field(description="Epoch seconds the merge landed.")
    tasks: list[str]
    sha: str | None = None
    pr: LedgerPull | None = None
    appliedBy: str | None = Field(
        default=None,
        description="The parent merge's key whose pin bump applied this one; null until one has; absent on a merge of "
        "the main repository.",
    )
    applies: list[str] | None = None
    runs: dict[str, LedgerRun]
    fails: dict[str, LedgerFail]
    pinned: bool


class StripBucket(_Api):
    merges: int
    failed: int
    reruns: int


class MergeStrip(_Api):
    """The 24-hour strip of the merge ledger: per bucket, the merges, the failed ones and the forced reruns."""

    since: float
    bucket: float
    buckets: list[StripBucket]
