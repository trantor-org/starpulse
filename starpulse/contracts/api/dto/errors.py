"""The bodies a route answers with when it refuses."""

from typing import Any

from pydantic import Field

from starpulse.contracts.api._base import _Api


class ApiError(_Api):
    """Every refusal: what went wrong. A 400 for a body its request model refuses also names that `model` and the
    JSON `schema` a valid value of the refused field meets."""

    error: str
    model: str | None = None
    field_schema: dict[str, Any] | None = Field(None, alias="schema")


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


class NotHolder(ApiError):
    """A link request from a session that does not hold the task: the session, and the session that does (None: none)."""

    session: str
    holder: str | None = None


class DeliveredElsewhere(ApiError):
    """A `delivers` link of a pull request that already delivers another task, named by UUID and current handle."""

    ref: str
    task: str
    handle: str


class UnrecognisedUrl(ApiError):
    """A URL no configured forge adapter recognises: the URL and the adapter instances that were asked."""

    url: str
    adapters: list[str]
