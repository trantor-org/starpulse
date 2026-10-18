"""`/api/level/what-if`."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.trajectories import ChainState


class Change(_Api):
    before: float
    after: float
    change: float


class WhatIf(_Api):
    """`GET /api/level/what-if`: the chain with one transition's probability changed, from the usual first state."""

    now: float
    window_s: float
    history_s: float
    machine: str
    goal: str
    ended: int
    # `from` is a Python keyword.
    origin: str = Field(alias="from")
    to: str
    p: float
    was: float
    n: int
    start: str
    p_goal: Change
    expected_days: Change
    chain: dict[str, ChainState]
