"""`/api/harnesses` and `/api/history-window`."""

from __future__ import annotations

from starpulse.contracts.api._base import _Api


class HarnessTier(_Api):
    model: str
    efforts: list[str]
    models: dict[str, str] | None = None
    """Per-effort model ids when a harness embeds effort in the model id; omitted when every effort shares `model`."""
    run_efforts: dict[str, str] | None = None
    """The effort a session for each board effort runs at; omitted when every session runs at its board effort."""


class HarnessBody(_Api):
    name: str
    label: str
    sessions: bool
    reason: str | None
    tiers: dict[str, HarnessTier]


class Harnesses(_Api):
    """`GET /api/harnesses`: the tiers in order and each harness with its models and efforts."""

    tiers: list[str]
    harnesses: list[HarnessBody]


class WindowState(_Api):
    """`/api/history-window`: the effective window, the declared default, and whether Admin's override is in effect."""

    hours: float
    default: float
    overridden: bool
