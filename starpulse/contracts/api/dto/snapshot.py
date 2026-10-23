"""The snapshot `/api/snapshot` sends, its pieces, and the `/api/events` deltas and events."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.adapters import Move, Pool
from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.cue import Cue, Pull
from starpulse.contracts.api.dto.dag import DagBody, Domain
from starpulse.contracts.api.dto.flow import FlowSnapshot, Settled
from starpulse.contracts.api.dto.ledger import LedgerRow, MergeStrip
from starpulse.contracts.api.dto.task import RawTask


class Capabilities(_Api):
    """What the board writes beyond moves: the page draws Edit, Archive… and New task only for what its board does."""

    edit: bool
    archive: bool
    create: bool | None = None


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
    attention: str | None = Field(default=None, description="Where a task waits on a person.")
    startable: list[str] = Field(default_factory=list, description="The States a session starts a task from.")


class Claim(_Api):
    reason: str
    at: float


class MachinePage(_Api):
    """The first page of machines entered from `open`, by name; their bodies are in the snapshot's `flows`."""

    open: str | None
    machines: list[str]
    more: bool


class MachineEntryFrom(_Api):
    machine: str
    state: str


class MachineEntry(_Api):
    at: float
    machine: str
    row: str
    # `from` is a Python keyword.
    origin: MachineEntryFrom | None = Field(alias="from")
    dag: str | None


class MachineStrip(_Api):
    """The last 24 hours of machine entries, counted over every machine."""

    entries: list[MachineEntry]


class Rating(_Api):
    """A task's latest pass/fail rating: its verdict, the reason it names (empty when none), when it was set (epoch
    seconds) and how many changes the task's rating has had."""

    verdict: str
    reason: str
    at: float
    changes: int


class Snapshot(_Api):
    graphs: list[str] = Field(description="Every lifecycle machine the server draws, and `runs`.")
    domains: list[Domain] | None = Field(default=None, description="The DAG domains.")
    cues: list[Cue] | None = Field(default=None, description="The DAGs cued by a Board event.")
    boardUrl: str | None = Field(default=None, description="The Backlog board a task links into.")
    hint: str | None = Field(
        default=None,
        description="A Backlog.md project found beside the config while the default board is shown, and how to switch "
        "to it.",
    )
    dags: list[DagBody]
    pools: list[Pool] | None = Field(default=None, description="The concurrency pools the DAGs run on.")
    flows: list[FlowSnapshot]
    machinePage: MachinePage | None = None
    machineStrip: MachineStrip | None = None
    pulls: dict[str, list[Pull]] | None = Field(default=None, description="Each open task's pull requests, by task id.")
    claims: dict[str, Claim] | None = Field(
        default=None,
        description="Each task's latest In Progress claim the board writer refused an agent, and when (epoch seconds).",
    )
    mergeStrip: MergeStrip | None = None
    mergePins: list[LedgerRow] | None = Field(
        default=None, description="The pinned merge rows of the last day that the newest page leaves out."
    )
    roles: Roles | None = Field(default=None, description="Which State plays which part on the board.")
    capabilities: Capabilities | None = Field(
        default=None,
        description="What the board writes: the task modal draws Edit and Archive only when its board does.",
    )
    settled: dict[str, Settled]
    milestone_done: dict[str, int] | None = Field(
        default=None,
        description="How many tasks each milestone has completed, counted over every settled task though `settled` "
        "holds only the recent ones.",
    )
    cold_done: list[str] | None = Field(
        default=None,
        description="The ids of the done tasks past 24 h that the board feed holds as a stub, left out of `flows`: "
        "the full view (`?view=full`) only, the page reads them from `/api/done` and `/api/task/<id>`.",
    )
    ratings: dict[str, Rating] | None = Field(
        default=None, description="Each rated task's latest pass/fail rating, by task id; a task never rated is absent."
    )
    move_sets: dict[str, dict[str, Move]] | None = Field(
        default=None, description="Each distinct set of Board-column verdicts a task's `move_set` names, by key."
    )
    error: str | None
    reading: bool | None = Field(
        default=None,
        description="True while a just-started server is still reading its board: its Board is partial until a "
        "snapshot without it follows.",
    )
    now: float


class TaskDelta(_Api):
    """A Board task that moved (`agent` null once it left the lanes)."""

    id: str
    agent: RawTask | None
    settled: Settled | None


class MoveDelta(_Api):
    """A task a machine event placed on another machine."""

    machine: str
    id: str
    agent: RawTask


class DagsDelta(_Api):
    """A runs instance's workflows."""

    dags: list[DagBody]
    pools: list[Pool] | None = None
    error: str | None


class PullsDelta(_Api):
    pulls: dict[str, list[Pull]]


class ClaimDelta(_Api):
    task: str
    reason: str
    at: float


class LedgersDelta(_Api):
    """The merge strip and pins since the last event, whole. A Ledger's rows are not here: a page that has one open
    reads `GET /api/ledger/<event>/events`."""

    mergeStrip: MergeStrip | None
    mergePins: list[LedgerRow]


class BuildEvent(_Api):
    """The page build the server serves, sent right after each connect's snapshot: a hash of the built page's `index.html`,
    which names every chunk it loads by its digest. A page that holds another build than the one it is named is out of date."""

    id: str


class RestartingEvent(_Api):
    """The server was told to stop and will not answer after this: sent to every open stream before it exits."""

    at: float  #: when the server announced it, in epoch seconds
