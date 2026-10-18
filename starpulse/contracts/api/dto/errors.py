"""The bodies a route answers with when it refuses."""

from __future__ import annotations

from typing import Any

from starpulse.contracts.api._base import _Api


class ApiError(_Api):
    """Every refusal: what went wrong."""

    error: str


class SkillRefusal(ApiError):
    """A refusal a skill satisfies: the skill that produces what the guard needs."""

    skill: str


class StaleEdit(ApiError):
    """An edit refused because a field changed since the page read it: those fields with their current values."""

    stale: list[str]
    current: dict[str, Any]


class WindowTooLong(ApiError):
    """A level or telemetry window longer than its history, with the history's length."""

    history_s: float
