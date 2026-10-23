"""A Board task as the page reads it: criteria, runs and the raw record."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.adapters import Move
from starpulse.contracts.api._base import _Api


class TrailStep(_Api):
    state: str
    event: str
    at: float


class TaskCriterion(_Api):
    """One acceptance criterion of a Board task and whether it is checked."""

    text: str
    checked: bool


class TaskRun(_Api):
    """One scheduler run a task's id names, linked to the run's own page."""

    url: str
    status: str
    started_at: str = Field(alias="startedAt")


class RawTask(_Api):
    """A Backlog task. On the board its state is its lane; on every other machine, the state its latest machine event left it in."""

    id: str
    title: str
    state: str
    model: str
    profile: str | None = Field(
        default=None, description="The agent profile a Board task is routed to; empty when none, absent off the Board."
    )
    assignee: str | None = Field(
        default=None,
        description="The session that last claimed a Board task; empty when none has, absent off the Board.",
    )
    labels: list[str] | None = None
    dependencies: list[str] | None = Field(default=None, description="A task's dependencies, as task ids.")
    prs: list[str] | None = Field(default=None, description="A task's pull requests: the PR URLs among its references.")
    runs: list[TaskRun] | None = Field(
        default=None, description="A task's scheduler runs: those whose run id names it (`dag-run-task-<N>-<ts>`)."
    )
    task: str | None = Field(default=None, description="A machine's task: the id of the Backlog task its events name.")
    steps: int | None = None
    trail: list[TrailStep] | None = None
    active: float | None = None
    description: str | None = Field(default=None, description="A task's Backlog description.")
    milestone: str | None = Field(
        default=None, description="A Board task's milestone; empty or absent when it has none."
    )
    type: str | None = Field(default=None, description="A Board task's type; empty or absent when it has none.")
    impact: str | None = Field(
        default=None, description="A Board task's Impact (low, medium or high); empty or absent when it has none."
    )
    urgency: str | None = Field(
        default=None, description="A Board task's Urgency (low, medium or high); empty or absent when it has none."
    )
    criteria: list[TaskCriterion] | None = Field(
        default=None, description="A Board task's acceptance criteria in file order; absent off the Board."
    )
    pause_reason: str | None = Field(
        default=None,
        description="Why a paused Board task waits for a person; empty when it is not paused, absent off the Board.",
    )
    previous: str | None = Field(
        default=None, description="The Board lane the task left on its last move; absent before it has moved."
    )
    moves: dict[str, Move] | None = Field(
        default=None,
        description="The verdict on each Board column the task may move to, by state id; a snapshot names the set in "
        "`move_set` instead, and a delta carries it here.",
    )
    move_set: str | None = Field(
        default=None,
        description="A snapshot's key into its `move_sets` for the task's `moves`; absent when it has none.",
    )
    entered: float | None = Field(
        default=None,
        description="When a Board task entered its lane, epoch seconds; absent when the server holds no time for it.",
    )
    created: float | None = Field(
        default=None, description="When a Board task was created, in epoch seconds; null or absent when unknown."
    )
    workable: bool | None = Field(default=None, description="Whether a Board task can be worked now.")
    workable_since: float | None = Field(
        default=None, description="Since when a workable Board task has been, epoch seconds."
    )
