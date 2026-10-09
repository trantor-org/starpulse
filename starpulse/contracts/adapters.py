"""The contracts an adapter writes (board, machine events, runs and their pools, insights) and the task key it declares.

An adapter is a producer of these records for StarPulse: a Backlog.md or Jira reader writes
`BoardTask`s, a harness or git hook writes `MachineEvent`s, and a scheduler reader writes `Dag`s, each with its
`ActiveRun`s, and the `Pool`s they run on. An external engine, a fourth kind of producer, posts `Finding`s through the
hub's insights API; a finding is about a team, machine, state or task, and the contract has no
field for a person.
Each model is also published as a JSON Schema under `schemas/`, regenerated with
`python -m starpulse.contracts`; `starpulse._internal.kit.adapter_kit` runs an adapter's output against them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CONTRACTS",
    "EVENT_STREAMS",
    "FINDING_TEXT_MAX",
    "SCHEMAS",
    "ActiveRun",
    "BoardTask",
    "Dag",
    "Evidence",
    "Finding",
    "FindingEngine",
    "FindingScope",
    "LaneEvent",
    "MachineEvent",
    "Move",
    "Pool",
    "RecentRun",
    "RunEvent",
    "RunStatus",
    "RunsSink",
    "StartFailedError",
    "Step",
    "TaskKeys",
]


class StartFailedError(Exception):
    """A runs adapter's start capability could not start the workflow; its message is the reason shown to the operator."""


@dataclass(frozen=True)
class TaskKeys:
    """How one adapter names its tasks, and which branch belongs to which task."""

    #: Matches a whole task key, e.g. `PROJ-45` or `ENG-123`.
    key: re.Pattern[str]
    #: Matches a branch name, bare or under `refs/heads/`; group 1 is the key, or what `key_format` wraps into it.
    branch: re.Pattern[str]
    #: Wraps group 1 of `branch` into the key: `PROJ-{}` turns the `45` of `feature/proj-45-x` into `PROJ-45`.
    key_format: str = "{}"

    def matches(self, task: str) -> bool:
        """Whether `task` is a whole key of this scheme."""
        return self.key.fullmatch(task) is not None

    def for_branch(self, ref: str | None) -> str | None:
        """The task key a branch names, or None for a branch that names no task."""
        match = self.branch.match(ref) if ref else None
        return self.key_format.format(match[1]) if match else None


class _Contract(BaseModel):
    """A record StarPulse reads: unknown fields are an error, so a misspelt one is not silently lost."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Move(_Contract):
    """The verdict on moving a task to one column: allowed, or guarded by a declared rule."""

    allowed: bool = Field(description="False when a guard the board writer enforces would refuse the move.")
    reason: str = Field(default="", description="What the refusing guard needs; empty when the move is allowed.")
    skill: str = Field(default="", description="The skill that produces what the guard needs; empty when allowed.")
    writers: tuple[str, ...] = Field(
        default=(),
        description="The actors the machine YAML declares for the event behind the move; empty when it declares none, "
        "and then any actor may make it.",
    )

    def permits(self, actor: str) -> bool:
        """False when the machine declares writers for the event and `actor` is none of them."""
        return not self.writers or actor in self.writers

    def for_actor(self, actor: str) -> Move:
        """The verdict as `actor` meets it: this move, or a refusal when `actor` is not among its writers."""
        if self.permits(actor):
            return self
        reason = self.reason or f"made by {', '.join(self.writers)}, not {actor}"
        return self.model_copy(update={"allowed": False, "reason": reason})


class BoardTask(_Contract):
    """One task on the board, as the latest observation of it."""

    id: str = Field(description="The task key, matching the adapter's declared `TaskKeys.key` (`PROJ-45`, `ENG-123`).")
    title: str = Field(description="The task's one-line title.")
    team: str = Field(
        pattern=r"\S",
        description="The team key the adapter derived from the tracker's own structure: a Backlog.md project, a Jira "
        "project or board, a GitHub repository. Never blank, so a task that belongs to no project is refused rather "
        "than counted under a default team.",
    )
    lane: str = Field(
        description="The id of the Board machine state the task is in (`in_progress`): its status, lower-cased, spaces as `_`."
    )
    dependencies: tuple[str, ...] = Field(default=(), description="Keys of the tasks this one waits on.")
    references: tuple[str, ...] = Field(
        default=(), description="Links and paths the task cites; the pull request URLs among them are drawn as its PRs."
    )
    settled: Literal["completed", "archived"] | None = Field(
        default=None,
        description="Set when the task has left the lanes for good, `completed` or `archived`; `lane` is then ignored.",
    )
    created_at: float | None = Field(
        default=None, description="When the task was created, in epoch seconds; None when the board does not say."
    )
    settled_at: float | None = Field(
        default=None,
        description="When a settled task settled, in epoch seconds; None when the board does not say or it is not settled.",
    )
    observed_at: float | None = Field(
        default=None,
        description="When the board saw the task in this state, in epoch seconds; None when it does not say. A move "
        "read live is dated by it, not by when StarPulse read it.",
    )
    assignee: str = Field(default="", description="Who or which agent model holds the task; empty when unassigned.")
    holder: str = Field(
        default="",
        description="The session that last claimed the task, as its harness names it; empty when none has. `assignee` stays who or which agent model the task is for.",
    )
    labels: tuple[str, ...] = Field(default=(), description="The task's labels.")
    milestone: str = Field(default="", description="The milestone the task belongs to; empty when it has none.")
    description: str = Field(default="", description="The task's description text, shown when the task is opened.")
    acceptance_criteria: tuple[str, ...] = Field(
        default=(),
        description="The text of each acceptance criterion, searched with the title and description; empty when the board keeps none.",
    )
    notes: str = Field(
        default="",
        description="The task's running notes, searched with the title and description; empty when the board keeps none.",
    )
    moves: dict[str, Move] = Field(
        default_factory=dict,
        description="The verdict on each Board column the task may move to, by state id; empty for a settled task.",
    )


class MachineEvent(_Contract):
    """One event a lifecycle machine saw, keyed by the task or run it moved; the `machine:events` entry's fields."""

    event_id: str = Field(
        default="", description="The stream's unique id for the entry; absent from a record not read off a stream."
    )
    machine: str = Field(description="The machine's registry name (`in-progress`).")
    event: str = Field(description="The machine's own name for the event (`WORKTREE_READY`).")
    task: str | None = Field(default=None, description="The task key it moved; exactly one of `task` and `run` is set.")
    run: str | None = Field(default=None, description="The run id it moved; exactly one of `task` and `run` is set.")
    actor: str = Field(default="", description="Who or what fired the event: an agent, a hook, a DAG.")
    time: float = Field(
        description="When it happened, in epoch seconds; a stream carries it as text and it is read as a number."
    )

    @model_validator(mode="after")
    def _keyed_by_one(self) -> Self:
        if (self.task is None) == (self.run is None):
            raise ValueError("key a machine event by exactly one of task or run")
        return self


#: Every status a run or a step reports: an adapter maps its engine's states onto these and may keep the engine's own in `raw`.
RunStatus = Literal["not_started", "queued", "running", "succeeded", "failed", "aborted", "skipped"]


class Step(_Contract):
    """One step of a DAG in its latest run."""

    name: str = Field(description="The step's name, unique within its DAG.")
    depends: tuple[str, ...] = Field(description="Names of the steps that must finish before this one starts.")
    status: RunStatus = Field(description="The step's status in the latest run.")
    raw: str | None = Field(
        default=None, description="The engine's own status for the step when it differs from `status`, shown as is."
    )
    kind: str | None = Field(description="The phase kind the step declares (`agent`), or None when it declares none.")


class Dag(_Contract):
    """One DAG with its step graph and its latest run."""

    name: str = Field(description="The DAG's name, unique on its scheduler.")
    status: RunStatus = Field(description="The latest run's status (`not_started` before any run).")
    raw: str | None = Field(
        default=None, description="The engine's own status for the run when it differs from `status`, shown as is."
    )
    run_id: str = Field(alias="runId", description="The latest run's id; empty before any run.")
    started_at: str = Field(
        alias="startedAt",
        description="When the latest run started, ISO 8601 UTC (`2026-10-02T17:00:00Z`); empty before any run.",
    )
    finished_at: str = Field(
        alias="finishedAt",
        description="When the latest run ended, ISO 8601 UTC; empty while it runs or before any run.",
    )
    steps: tuple[Step, ...] = Field(description="The DAG's steps; empty when the scheduler cannot describe them.")
    active: tuple[ActiveRun, ...] = Field(
        default=(),
        description="Every run of the DAG that is running or queued now, longest-running first; empty when none "
        "is or the scheduler cannot list them.",
    )
    pool: str = Field(
        default="", description="The name of the concurrency `Pool` the DAG runs on; empty when it names none."
    )
    recent: tuple[RecentRun, ...] = Field(
        default=(),
        description="The DAG's runs of the last day with the parameters each started with and its per-step status, "
        "for the workflows a Board event cues or that write one; empty for any other or when the scheduler cannot "
        "list them.",
    )


class RecentRun(_Contract):
    """One run of a DAG within the last day, running or over, with the parameters it started with."""

    run_id: str = Field(alias="runId", description="The run's id.")
    status: RunStatus = Field(description="The run's status.")
    raw: str | None = Field(
        default=None, description="The engine's own status for the run when it differs from `status`, shown as is."
    )
    started_at: str = Field(
        alias="startedAt", description="When the run started, ISO 8601 UTC (`2026-10-02T17:00:00Z`)."
    )
    finished_at: str = Field(
        alias="finishedAt", description="When the run ended, ISO 8601 UTC; empty while it runs."
    )
    params: dict[str, str] = Field(
        description="The `KEY=value` parameters the run started with, by name; empty when it had none."
    )
    steps: dict[str, RunStatus] = Field(description="Each step the run reached by name with its status in this run.")


class ActiveRun(_Contract):
    """One run of a DAG that is running or queued now."""

    run_id: str = Field(alias="runId", description="The run's id.")
    status: RunStatus = Field(description="The run's status: `running` or `queued`.")
    raw: str | None = Field(
        default=None, description="The engine's own status for the run when it differs from `status`, shown as is."
    )
    started_at: str = Field(
        alias="startedAt",
        description="When the run started, or was queued while it waits, ISO 8601 UTC (`2026-10-02T17:00:00Z`).",
    )
    step: str = Field(
        description="The step the run entered last among those running; empty while it is queued or between steps."
    )
    step_started_at: str = Field(
        alias="stepStartedAt", description="When the run entered `step`, ISO 8601 UTC; empty when `step` is."
    )
    steps: dict[str, RunStatus] = Field(description="Each of the DAG's steps by name with its status in this run.")


class Pool(_Contract):
    """One concurrency pool: the cap on the runs that may execute at once, and the runs holding or awaiting it."""

    name: str = Field(description="The pool's name, unique on its scheduler; a DAG's `pool` names it.")
    cap: int = Field(ge=0, description="The most runs the pool lets execute at once.")
    running: int = Field(ge=0, description="The runs executing on the pool now.")
    queued: int = Field(ge=0, description="The runs waiting for the pool to have room.")


class RunsSink(Protocol):
    """Where a runs adapter's `follow(url, runs, log)` publishes the workflows and `Pool`s of its one instance, and says when it cannot read them.

    `pools` None keeps the last reported and a list replaces them, so an adapter that reports none passes `[]`.
    `startable`, when the adapter can start only some of its workflows, names those; None keeps the last report, and an
    adapter that never reports one is read as able to start every workflow.
    """

    def set_dags(
        self, dags: list | None, error: str | None, pools: list | None = None, startable: list[str] | None = None
    ) -> None: ...


class FindingEngine(_Contract):
    """The engine that wrote a finding."""

    name: str = Field(min_length=1, description="The engine's name, stable across its releases.")
    version: str = Field(min_length=1, description="The engine release that wrote the finding.")


class FindingScope(_Contract):
    """What a finding is about. Every field is optional and a finding may name none; there is no field for a person,
    so a finding about one cannot be written, and one that tries is refused as an unknown field."""

    team: str | None = Field(default=None, description="The team key the finding is about, as a board task's `team`.")
    machine: str | None = Field(default=None, description="The machine the finding is about, as `<repo>/<machine>`.")
    state: str | None = Field(default=None, description="The state of that machine the finding is about.")
    task: str | None = Field(default=None, description="The task key the finding is about.")


class Evidence(_Contract):
    """One thing a reader can open to check a finding: a labelled link, or a labelled query over the history store."""

    label: str = Field(min_length=1, description="What the link or query shows, in a few words.")
    url: str | None = Field(
        default=None, description="A link to the evidence; exactly one of `url` and `query` is set."
    )
    query: str | None = Field(
        default=None,
        description="A read-only query over the history store's tables that returns the evidence; exactly one of "
        "`url` and `query` is set.",
    )

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.url is None) == (self.query is None):
            raise ValueError("give evidence exactly one of url or query")
        return self


#: The longest finding text: a line in the page's rail, not a report.
FINDING_TEXT_MAX = 280


class Finding(_Contract):
    """One thing an external engine says about the flow, posted to `POST /api/insights`; a re-post of an `id` replaces it."""

    id: str = Field(min_length=1, description="The engine's stable key for the finding; posting it again replaces it.")
    engine: FindingEngine = Field(description="The engine that wrote it, by name and version.")
    scope: FindingScope = Field(
        default_factory=FindingScope, description="What it is about: a team, machine, state or task, each optional."
    )
    severity: Literal["info", "warn", "act"] = Field(description="How much attention it asks for.")
    text: str = Field(
        min_length=1,
        max_length=FINDING_TEXT_MAX,
        description="What the engine found, in plain text of at most 280 characters.",
    )
    evidence: tuple[Evidence, ...] = Field(default=(), description="Where a reader can check it.")
    created_at: float = Field(allow_inf_nan=False, description="When the engine wrote it, in epoch seconds.")
    expires_at: float | None = Field(
        default=None,
        allow_inf_nan=False,
        description="When the page should stop showing it, in epoch seconds, after `created_at`; None keeps it until it is retracted.",
    )

    @model_validator(mode="after")
    def _expires_after_creation(self) -> Self:
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class RunEvent(_Contract):
    """One workflow run, or one step of it, starting or ending; the `runs:events` entry's fields."""

    time: float = Field(ge=0, allow_inf_nan=False, description="When it happened, in epoch seconds.")
    phase: Literal["start", "end"] = Field(description="Whether the run or step started or ended.")
    workflow: str = Field(min_length=1, description="The workflow's name, unique on its scheduler.")
    run_id: str = Field(min_length=1, description="The run's id.")
    status: RunStatus = Field(description="The run's status, or the step's when `step` is set.")
    step: str = Field(default="", description="The step this entry reports; empty when it reports the run itself.")
    depends: tuple[str, ...] = Field(
        default=(), description="Names of the steps `step` waits on; empty when it waits on none, and needs `step`."
    )
    instance: str = Field(
        default="",
        description="The runs adapter instance whose token pushed the entry over HTTP; empty for an entry a hook emitted.",
    )

    @model_validator(mode="after")
    def _depends_names_a_step(self) -> Self:
        if self.depends and not self.step:
            raise ValueError("depends needs step")
        return self


class LaneEvent(_Contract):
    """One task entering a Board lane; the `board:lanes` entry's fields. It never carries a title, a description, a
    holder or any session detail."""

    task: str = Field(min_length=1, description="The task key that changed lane.")
    lane: str = Field(min_length=1, description="The id of the Board machine state the task entered.")
    time: float = Field(ge=0, allow_inf_nan=False, description="When the task entered the lane, in epoch seconds.")
    team: str = Field(default="", description="The task's team key; empty on an entry replayed from the history.")
    milestone: str = Field(default="", description="The task's milestone; empty when it has none.")
    labels: tuple[str, ...] = Field(default=(), description="The task's labels; empty when it has none.")
    assignee: str = Field(
        default="", description="Who or which agent model held the task; empty when unassigned, and a person's name."
    )


#: Each contract's model, by the name its checked-in schema file carries.
CONTRACTS: dict[str, type[BaseModel]] = {
    "board": BoardTask,
    "machine-events": MachineEvent,
    "run-events": RunEvent,
    "lane-events": LaneEvent,
    "runs": Dag,
    "pools": Pool,
    "insights": Finding,
}
#: The contract of each stream of the event log (`starpulse.event_log`), by the name `CONTRACTS` gives it: the
#: `fields` of an `Entry` read from that stream are a record of that model. A package test fails for a stream a
#: producer declares that is missing here.
EVENT_STREAMS: dict[str, str] = {
    "machine:events": "machine-events",
    "runs:events": "run-events",
    "board:lanes": "lane-events",
}
#: Each contract's JSON Schema, by the same names.
SCHEMAS: dict[str, dict] = {name: model.model_json_schema() for name, model in CONTRACTS.items()}
SCHEMA_DIR = Path(__file__).parents[1] / "schemas"

