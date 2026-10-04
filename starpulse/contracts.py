"""The three contracts an adapter writes (board, machine events, runs) and the task key it declares.

An adapter is a producer of these records for StarPulse: a Backlog.md or Jira reader writes
`BoardTask`s, a harness or git hook writes `MachineEvent`s, and a scheduler reader writes `Dag`s.
Each model is also published as a JSON Schema under `schemas/`, regenerated with
`python -m starpulse.contracts`; `starpulse.adapter_kit` runs an adapter's output against them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    assignee: str = Field(default="", description="Who or which agent model holds the task; empty when unassigned.")
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


#: Each contract's model, by the name its checked-in schema file carries.
CONTRACTS: dict[str, type[BaseModel]] = {"board": BoardTask, "machine-events": MachineEvent, "runs": Dag}
#: Each contract's JSON Schema, by the same names.
SCHEMAS: dict[str, dict] = {name: model.model_json_schema() for name, model in CONTRACTS.items()}
SCHEMA_DIR = Path(__file__).parent / "schemas"


if __name__ == "__main__":
    SCHEMA_DIR.mkdir(exist_ok=True)
    for schema_name, schema in SCHEMAS.items():
        (SCHEMA_DIR / f"{schema_name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
