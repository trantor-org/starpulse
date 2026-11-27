"""The snapshot `/api/snapshot` sends and its pieces."""

from pydantic import Field

from starpulse.contracts.adapters import Pool
from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.cue import Cue, Pull
from starpulse.contracts.api.dto.dag import DagBody, Domain
from starpulse.contracts.api.dto.flow import FlowSnapshot, Settled
from starpulse.contracts.api.dto.ledger import LedgerRow, MergeStrip


class Roles(_Api):
    """Which of the board's States play which part, as its machine declares them: a client reads these and never a
    State's name."""

    initial: str | None = Field(default=None, description="Where a task starts.")
    final: str | None = Field(default=None, description="Where a task is settled for good.")
    done: str | None = Field(default=None, description="Where the work is done: a resting State, else the final one.")
    working: str | None = Field(default=None, description="Where a session works a task.")
    ready: str | None = Field(default=None, description="Where a task waits to be picked up.")
    waiting: str | None = Field(default=None, description="Where a task waits on its Start Criteria or dependencies.")
    review: str | None = Field(default=None, description="Where a task waits on its pull request.")
    verifying: str | None = Field(default=None, description="Where a merged task rests while its post-merge QA runs.")
    attention: str | None = Field(default=None, description="Where a task waits on a person.")
    startable: list[str] = Field(default_factory=list, description="The States a session starts a task from.")
    lanes: list[str] = Field(
        default_factory=list,
        description="The open lanes the kanban and the Star Map draw, in the machine's order: every State but the initial and final.",
    )


class Snapshot(_Api):
    graphs: list[str] = Field(description="Every lifecycle machine the server draws, and `runs`.")
    domains: list[Domain] | None = Field(default=None, description="The DAG domains.")
    cues: list[Cue] | None = Field(default=None, description="The DAGs cued by a Board event.")
    dags: list[DagBody]
    pools: list[Pool] | None = Field(default=None, description="The concurrency pools the DAGs run on.")
    flows: list[FlowSnapshot]
    pulls: dict[str, list[Pull]] | None = Field(default=None, description="Each open task's pull requests, by task id.")
    mergeStrip: MergeStrip | None = None
    mergePins: list[LedgerRow] | None = Field(
        default=None, description="The pinned merge rows of the last day that the newest page leaves out."
    )
    roles: Roles | None = Field(default=None, description="Which State plays which part on the board.")
    settled: dict[str, Settled]
    milestone_done: dict[str, int] | None = Field(
        default=None,
        description="How many tasks each milestone has completed, counted over every settled task though `settled` "
        "holds only the recent ones.",
    )
    cold_done: list[str] | None = Field(
        default=None,
        description="The ids of the done tasks from before local midnight that the board feed holds as a stub, left out of `flows`: "
        "the stored body never carries them (the page reads them from `/api/done` and `/api/task/<id>`), a feed's own snapshot does.",
    )
    archived_today: int | None = Field(
        default=None, description="How many tasks were archived since local midnight, the window of the Done count."
    )
    interactive: dict[str, bool] | None = Field(
        default=None,
        description="Each task an accepted take-over made interactive, by task id; a task never taken over is absent.",
    )
    error: str | None
    reading: bool | None = Field(
        default=None,
        description="True while a just-started server is still reading its board: its Board is partial until a "
        "snapshot without it follows.",
    )
    now: float
