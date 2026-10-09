"""The `[autopilot]` config block: the policy the autopilot loop runs under, every key optional.

With no block the autopilot has everything it needs: the board's initial lane is the eligible lane, the built-in
tier weights price a task by its tier, an unsized task counts as `unsized_points`, and the four capacity
dimensions have the limits below, and a session idle for `idle_minutes` with its task still open is settled to Needs
attention. `lane`, `review_lane`, `unsized_points`, `idle_minutes`, `[autopilot.tier_weights]` and `[autopilot.limits]`
each override one default; a key left out keeps its default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["DIMENSIONS", "Autopilot", "AutopilotError", "parse_autopilot"]

#: The capacity dimensions: host CPU and memory (percent), autopilot sessions in flight, and review-lane points.
DIMENSIONS = ("cpu", "memory", "sessions", "review")

_KEYS = {"lane", "review_lane", "unsized_points", "idle_minutes", "tier_weights", "limits"}


class AutopilotError(ValueError):
    """The block cannot be run from; the message names the key to fix."""


@dataclass(frozen=True)
class Autopilot:
    lane: str | None = None
    """The lane whose tasks are eligible; none: the board's initial lane."""
    review_lane: str = "review"
    """The lane whose tasks' points are the review load."""
    unsized_points: int = 3
    """The points a task with no `size-N` label counts as."""
    idle_minutes: float = 30
    """How long a session may sit with no event before its still-open task is settled to Needs attention."""
    tier_weights: Mapping[str, float] = field(default_factory=lambda: {"fast": 1, "standard": 2, "deep": 4})
    """What a point costs on each agent tier: a task's demand starts from its points times its tier's weight."""
    limits: Mapping[str, float] = field(
        default_factory=lambda: {"cpu": 80, "memory": 80, "sessions": 2, "review": 20}
    )
    """Each dimension's limit: CPU and memory in percent, sessions as a count, review in points."""

    def eligible_lane(self, initial: str) -> str:
        """The lane autopilot admits from: the configured one, else the board's `initial` lane."""
        return self.lane or initial


def _lane(value: object, key: str) -> str | None:
    if value is not None and not (isinstance(value, str) and value):
        raise AutopilotError(f"autopilot {key} must be the id of a lane")
    return value


def _number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise AutopilotError(f"autopilot {key} must be a number above zero")
    return value


def _table(raw: object, key: str, known: Mapping[str, float] | None) -> dict[str, float]:
    """The numbers of `[autopilot.<key>]`; with `known`, a name outside it is refused."""
    if not isinstance(raw, dict):
        raise AutopilotError(f"autopilot {key} must be an [autopilot.{key}] table")
    if known is not None and (unknown := sorted(raw.keys() - known.keys())):
        raise AutopilotError(f"autopilot {key}: unknown {', '.join(unknown)}; known: {', '.join(known)}")
    return {name: _number(value, name) for name, value in raw.items()}


def parse_autopilot(raw: object) -> Autopilot:
    """The `[autopilot]` table as policy, or the defaults for `None`; each refusal names the key to fix."""
    if raw is None:
        return Autopilot()
    if not isinstance(raw, dict):
        raise AutopilotError("autopilot must be an [autopilot] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise AutopilotError(f"unknown autopilot key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    defaults = Autopilot()
    lane, review_lane = _lane(raw.get("lane"), "lane"), _lane(raw.get("review_lane", defaults.review_lane), "review_lane")
    unsized = raw.get("unsized_points", defaults.unsized_points)
    if isinstance(unsized, bool) or not isinstance(unsized, int) or unsized < 1:
        raise AutopilotError("autopilot unsized_points must be a whole number of 1 or more")
    idle = _number(raw.get("idle_minutes", defaults.idle_minutes), "idle_minutes")
    weights = _table(raw.get("tier_weights", {}), "tier_weights", None)
    limits = _table(raw.get("limits", {}), "limits", defaults.limits)
    return Autopilot(
        lane,
        review_lane,
        unsized,
        idle,
        {**defaults.tier_weights, **weights},
        {**defaults.limits, **limits},
    )
