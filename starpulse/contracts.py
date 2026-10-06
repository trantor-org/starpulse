"""The contracts an adapter writes (board, machine events, runs and their pools) and the task key it declares.

An adapter is a producer of these records for StarPulse: a Backlog.md or Jira reader writes
`BoardTask`s, a harness or git hook writes `MachineEvent`s, and a scheduler reader writes `Dag`s, each with its
`ActiveRun`s, and the `Pool`s they run on.
Each model is also published as a JSON Schema under `schemas/`, regenerated with
`python -m starpulse.contracts`; `starpulse.adapter_kit` runs an adapter's output against them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CONTRACTS",
    "SCHEMAS",
    "ActiveRun",
    "BoardTask",
    "Dag",
    "MachineEvent",
    "Move",
    "Pool",
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
    assignee: str = Field(default="", description="Who or which agent model holds the task; empty when unassigned.")
    holder: str = Field(
        default="",
        description="The session that last claimed the task, as its harness names it; empty when none has. `assignee` stays who or which agent model the task is for.",
    )
    labels: tuple[str, ...] = Field(default=(), description="The task's labels.")
    milestone: str = Field(default="", description="The milestone the task belongs to; empty when it has none.")
    description: str = Field(default="", description="The task's description text, shown when the task is opened.")
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
    """

    def set_dags(self, dags: list | None, error: str | None, pools: list | None = None) -> None: ...


#: Each contract's model, by the name its checked-in schema file carries.
CONTRACTS: dict[str, type[BaseModel]] = {
    "board": BoardTask,
    "machine-events": MachineEvent,
    "runs": Dag,
    "pools": Pool,
}
#: Each contract's JSON Schema, by the same names.
SCHEMAS: dict[str, dict] = {name: model.model_json_schema() for name, model in CONTRACTS.items()}
SCHEMA_DIR = Path(__file__).parent / "schemas"


if __name__ == "__main__":
    SCHEMA_DIR.mkdir(exist_ok=True)
    for schema_name, schema in SCHEMAS.items():
        (SCHEMA_DIR / f"{schema_name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
