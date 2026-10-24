"""The paged and read routes of the ledgers and the machines view."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.flow import FlowSnapshot, Stuck, Tie
from starpulse.contracts.api.dto.ledger import LedgerRow
from starpulse.contracts.api.dto.task import RawTask


class LedgerPage(_Api):
    """`GET /api/ledger/<event>`, and the first event of `GET /api/ledger/<event>/events`: a Ledger's rows, newest first,
    and whether older ones remain."""

    rows: list[LedgerRow]
    more: bool


class DonePage(_Api):
    """`GET /api/done`: the next page of done tasks past their hot day, newest first, and whether older ones remain."""

    tasks: list[RawTask]
    more: bool


class LedgerChange(_Api):
    """A later event of `GET /api/ledger/<event>/events`: the rows that are new or differ; every other row stands."""

    rows: list[LedgerRow]


class MachineRow(FlowSnapshot):
    """A machine of `GET /api/machines`: whole, with its derivation."""

    ties: list[Tie]
    parent: str | None
    depth: int
    chain: list[str]
    nested: list[str]
    last: float | None
    stuck: Stuck | None


class Machines(_Api):
    """`GET /api/machines`: the next page of machines entered from `open`."""

    open: str | None
    machines: list[MachineRow]
    more: bool


class LaneStep(_Api):
    at: float
    # `from` is a Python keyword.
    origin: str | None = Field(alias="from")
    to: str
    # Present only where the write named its actor.
    by: str | None = None


class MachineStep(_Api):
    at: float
    event: str
    state: str


class LaneHistory(_Api):
    """`GET /api/history?task=`: a task's lane changes, oldest first."""

    task: str
    path: list[LaneStep]
