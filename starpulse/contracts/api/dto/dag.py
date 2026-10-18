"""The DAGs and domains the page draws."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.adapters import ActiveRun, RunStatus, Step
from starpulse.contracts.api._base import _Api


class DagBody(_Api):
    """A runs workflow as the page draws it: the latest run, the runs in flight and the pool it runs on."""

    name: str
    status: RunStatus
    raw: str | None = Field(default=None, description="The engine's own status when it differs from `status`.")
    runId: str
    startedAt: str
    finishedAt: str
    steps: list[Step]
    active: list[ActiveRun] | None = Field(
        default=None, description="Every running or queued run of the workflow, including concurrent ones."
    )
    pool: str | None = Field(default=None, description="The name of the pool the workflow runs on; empty when none.")


class DomainDag(_Api):
    name: str
    runSafe: bool


class DomainProcess(_Api):
    """A named package of a domain's DAGs."""

    name: str
    dags: list[DomainDag]


class Domain(_Api):
    """A domain's DAGs, and whether each is declared safe to run from the page; `processes` package them when configured."""

    name: str
    dags: list[DomainDag]
    processes: list[DomainProcess] = Field(default_factory=list)
