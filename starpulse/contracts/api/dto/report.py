"""`/api/doctor`: the contract report."""

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
