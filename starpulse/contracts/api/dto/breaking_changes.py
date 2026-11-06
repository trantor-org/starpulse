"""`/api/breaking-changes`: the commits that broke the default branch."""

from __future__ import annotations

from starpulse.contracts.api._base import _Api


class BreakingDetection(_Api):
    detector: str
    outcome: str | None = None
    evidence: str | None = None
    at: float


class BreakingChange(_Api):
    commit: str
    pr: int | None = None
    task: str | None = None
    outcome: str | None = None
    first_seen: float
    postmortem_task: str | None = None
    detections: list[BreakingDetection]


class BreakingChanges(_Api):
    """`GET /api/breaking-changes[?open=1]`: each commit once, oldest first; `open=1` keeps those with no postmortem."""

    changes: list[BreakingChange]
