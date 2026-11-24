"""The DAGs and domains the page draws."""

from pydantic import Field

from starpulse.contracts.adapters import ActiveRun, RecentRun, Rerun, RunStats, RunStatus, Step
from starpulse.contracts.api._base import _Api


class DagBody(_Api):
    """A runs workflow as the page draws it: the latest run, the runs in flight and the pool it runs on."""

    name: str
    status: RunStatus
    raw: str | None = Field(default=None, description="The engine's own status when it differs from `status`.")
    runId: str
    startUrl: str = Field(description="The runner's own start page for the workflow; empty when its runner has none.")
    startedAt: str
    finishedAt: str
    steps: list[Step]
    schedule: list[str] = Field(
        description="The cron expressions that start the workflow; empty when it runs only when asked for."
    )
    stats: RunStats | None = Field(
        description="The workflow's runs over the last seven days; None when it never ran or they are unknown."
    )
    rerun: Rerun | None = Field(
        description="What the workflow declares about a rerun repeating its effects; None when it declares nothing."
    )
    active: list[ActiveRun] | None = Field(
        default=None, description="Every running or queued run of the workflow, including concurrent ones."
    )
    failed: list[RecentRun] | None = Field(
        default=None, description="The newest failed runs of the workflow, newest first; absent when none failed."
    )
    closed: list[RecentRun] | None = Field(
        default=None, description="The newest closed runs of the workflow of any status, newest first; absent when none ran."
    )
    pool: str | None = Field(default=None, description="The name of the pool the workflow runs on; empty when none.")


class Jobs(_Api):
    """`POST /api/jobs`: every runs workflow as the snapshot lists it, and the error a runs instance reported, with the
    stream position the list was read at: a `jobChanges` subscription from it carries every change after."""

    position: int
    items: list[DagBody]
    error: str | None


class DomainDag(_Api):
    name: str


class DomainProcess(_Api):
    """A named package of a domain's DAGs."""

    name: str
    dags: list[DomainDag]


class Domain(_Api):
    """A domain's DAGs; `processes` package them when configured."""

    name: str
    dags: list[DomainDag]
    processes: list[DomainProcess] = Field(default_factory=list)
