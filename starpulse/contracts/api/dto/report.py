"""`/api/doctor`: the contract report; `/api/ready`: the readiness report."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from starpulse.contracts.api._base import _Api


class ContractCheck(_Api):
    """One check of the contract between the config and the machines' DAG cues."""

    check: str = Field(description="`cue:<dag>` or `repo:<name>`.")
    status: Literal["pass", "warn", "fail"]
    reason: str


class ContractReport(_Api):
    """The contract checks `starpulse doctor` runs; `ok` is false when any fails."""

    ok: bool
    checks: list[ContractCheck]


class ReadyComponent(_Api):
    """One part of the server `/api/ready` judges."""

    ready: bool
    detail: str


class ReadyReport(_Api):
    """Whether the server can serve the board; `components` names `store`, `board`, `writer` and `contexts`, and the route
    answers 503 with this body when any is not ready."""

    ready: bool
    components: dict[str, ReadyComponent]
