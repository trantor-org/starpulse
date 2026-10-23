"""The `[scheduler]` config block: the policy the scheduler loop runs under, every key optional.

With no block the scheduler has everything it needs: the board's initial lane is the eligible lane, the built-in
tier weights price a task by its tier, an unsized task counts as `unsized_points`, and the four capacity
dimensions have the limits below, and a session idle for `idle_minutes` with its task still open is settled to Needs
attention. `lane`, `review_lane`, `unsized_points`, `idle_minutes`, `state_dir`, `[scheduler.tier_weights]` and
`[scheduler.limits]` each override one default; a key left out keeps its default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["DIMENSIONS", "Scheduler", "SchedulerError", "parse_scheduler"]

#: The capacity dimensions: host CPU and memory (percent), scheduler sessions in flight, and review-lane points.
DIMENSIONS = ("cpu", "memory", "sessions", "review")

_KEYS = {
    "lane",
    "review_lane",
    "unsized_points",
    "idle_minutes",
    "state_dir",
    "tier_weights",
    "limits",
    "session_limits",
}


class SchedulerError(ValueError):
    """The block cannot be run from; the message names the key to fix."""


@dataclass(frozen=True)
class Scheduler:
    lane: str | None = None
    """The lane whose tasks are eligible; none: the board's initial lane."""
    review_lane: str | None = None
    """The lane whose tasks' points are the review load; none: the board's lane that waits on a pull request."""
    unsized_points: int = 3
    """The points a task with no `size-N` label counts as."""
    idle_minutes: float = 30
    """How long a session may sit with no event before its still-open task is settled to Needs attention."""
    state_dir: str | None = None
    """Where the files the switch and the run ledger were kept in before the store are imported from, relative to the config's directory; none: beside the config."""
    tier_weights: Mapping[str, float] = field(default_factory=lambda: {"fast": 1, "standard": 2, "deep": 4})
    """What a point costs on each agent tier: a task's demand starts from its points times its tier's weight."""
    limits: Mapping[str, float] = field(
        default_factory=lambda: {"cpu": 80, "memory": 80, "sessions": 2, "review": 20}
    )
    """Each dimension's limit: CPU and memory in percent, sessions as a count, review in points."""
    session_limits: Mapping[str, float] = field(default_factory=dict)
    """Per-harness session caps; a harness left out uses `limits["sessions"]`."""

    def eligible_lane(self, initial: str) -> str:
        """The lane scheduler admits from: the configured one, else the board's `initial` lane."""
        return self.lane or initial

    def reviewed_lane(self, review: str | None) -> str | None:
        """The lane whose points are the review load: the configured one, else the board's `review` lane."""
        return self.review_lane or review

    def session_limit(self, harness: str) -> float:
        """The session cap for `harness`: its own when set, else the shared `sessions` limit."""
        return float(self.session_limits.get(harness, self.limits["sessions"]))


def _lane(value: object, key: str) -> str | None:
    if value is not None and not (isinstance(value, str) and value):
        raise SchedulerError(f"scheduler {key} must be the id of a lane")
    return value


def _number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise SchedulerError(f"scheduler {key} must be a number above zero")
    return value


def _table(raw: object, key: str, known: Mapping[str, float] | None) -> dict[str, float]:
    """The numbers of `[scheduler.<key>]`; with `known`, a name outside it is refused."""
    if not isinstance(raw, dict):
        raise SchedulerError(f"scheduler {key} must be an [scheduler.{key}] table")
    if known is not None and (unknown := sorted(raw.keys() - known.keys())):
        raise SchedulerError(f"scheduler {key}: unknown {', '.join(unknown)}; known: {', '.join(known)}")
    return {name: _number(value, name) for name, value in raw.items()}


def parse_scheduler(raw: object) -> Scheduler:
    """The `[scheduler]` table as policy, or the defaults for `None`; each refusal names the key to fix."""
    if raw is None:
        return Scheduler()
    if not isinstance(raw, dict):
        raise SchedulerError("scheduler must be an [scheduler] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise SchedulerError(f"unknown scheduler key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    defaults = Scheduler()
    lane, review_lane = _lane(raw.get("lane"), "lane"), _lane(raw.get("review_lane"), "review_lane")
    unsized = raw.get("unsized_points", defaults.unsized_points)
    if isinstance(unsized, bool) or not isinstance(unsized, int) or unsized < 1:
        raise SchedulerError("scheduler unsized_points must be a whole number of 1 or more")
    idle = _number(raw.get("idle_minutes", defaults.idle_minutes), "idle_minutes")
    state_dir = raw.get("state_dir")
    if state_dir is not None and not (isinstance(state_dir, str) and state_dir):
        raise SchedulerError("scheduler state_dir must be a directory path")
    weights = _table(raw.get("tier_weights", {}), "tier_weights", None)
    limits = _table(raw.get("limits", {}), "limits", defaults.limits)
    session_limits = _table(raw.get("session_limits", {}), "session_limits", None)
    return Scheduler(
        lane,
        review_lane,
        unsized,
        idle,
        state_dir,
        {**defaults.tier_weights, **weights},
        {**defaults.limits, **limits},
        session_limits,
    )
