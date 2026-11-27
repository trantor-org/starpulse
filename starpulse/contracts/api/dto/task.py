"""A Board task as the page reads it: criteria, runs and the raw record."""

from typing import Any, Literal

from pydantic import Field

from starpulse.contracts.adapters import Move
from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.machine import HeldNext


#: One trail step: `[state, event, dt]`, the first two indexes into the flow's `names`, `dt` the milliseconds since the
#: step before it (the epoch for the first). A third-party machine's step adds its entry's event_id, which names the
#: subject it moved.
TrailPoint = tuple[int, int, int] | tuple[int, int, int, str]


class SessionActivity(_Api):
    """What a held working task's holder session is doing, read from its transcript when the snapshot is drawn."""

    state: Literal["working", "idle", "unknown"] = Field(
        description="`working` mid-turn, `idle` after a finished turn, `unknown` when no running session with a transcript holds the task."
    )
    last_turn_at: str | None = Field(default=None, description="When the session's last turn was written, ISO 8601; absent when unknown.")
    idle_s: int | None = Field(default=None, description="Seconds idle when the snapshot was drawn; present only when idle.")
    last_message: str | None = Field(
        default=None,
        description="The holder session's latest assistant message with text, cut to 2000 characters with an ellipsis; absent when it has not reported.",
    )
    last_message_at: str | None = Field(default=None, description="When `last_message` was written, ISO 8601; present with it.")


class TaskCriterion(_Api):
    """One acceptance criterion of a Board task and whether it is checked."""

    text: str
    checked: bool


class TaskRun(_Api):
    """One scheduler run a task's id names, linked to the run's own page."""

    url: str
    status: str
    started_at: str = Field(alias="startedAt")


class HeldSkill(_Api):
    name: str = Field(description="The skill machine the task is in.")
    states: list[str] = Field(description="The skill machine's state ids, in declared order.")
    current: str | None = Field(default=None, description="The state the task holds in the skill machine.")
    next: HeldNext | None = Field(default=None, description="The edge the skill declares; null when none is declared.")


class ClaimRelease(_Api):
    """The claim a Board task's claim-TTL sweep, or its idle holder's release, ended: when, and the session, last renewal and TTL."""

    at: float = Field(description="When the release was recorded, epoch seconds.")
    session: str
    last_renewal: float = Field(description="The session's last renewal before the release, epoch seconds.")
    ttl: float = Field(description="The claim TTL, in seconds, the session missed.")
    idle: bool = Field(default=False, description="The task actor ended this claim because its holder sat idle, not the TTL sweep.")


class Frozen(_Api):
    """The freeze the task actor holds a task in: who asked, when and why."""

    by: str
    at: str
    reason: str


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
    frozen: Frozen | None = Field(
        default=None, description="The freeze the task actor holds the task in; no move of it lands until it is lifted."
    )
    released: ClaimRelease | None = Field(
        default=None, description="The claim-TTL release a Board task's claim ended in; null when none ended it."
    )
    session_activity: SessionActivity | None = Field(
        default=None, description="What a held In Progress task's holder session is doing; absent off that lane or when unheld."
    )
    labels: list[str] | None = None
    dependencies: list[str] | None = Field(default=None, description="A task's dependencies, as task ids.")
    prs: list[str] | None = Field(default=None, description="A task's pull requests: the pages of the changes it has a `delivers` or `cites` link to.")
    delivered: list[str] | None = Field(default=None, description="A task's pull requests it has a `delivers` link to.")
    runs: list[TaskRun] | None = Field(
        default=None, description="A task's scheduler runs: those whose run id names it (`dag-run-task-<N>-<ts>`)."
    )
    task: str | None = Field(default=None, description="A machine's task: the id of the Backlog task its events name.")
    steps: int | None = None
    stored: dict[str, Any] | None = Field(
        default=None, description="A task's phase, substate, skill and open-dependency count, as its read-model row stores them."
    )
    trail: list[TrailPoint] | None = Field(
        default=None, description="A machine task's steps, as points indexing the `names` of the flow or move delta."
    )
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
    tier: str | None = Field(
        default=None,
        description="A Board task's tier (regression, bug, leverage, standard or decide); absent on a row an adapter does not tier.",
    )
    source: str | None = Field(
        default=None,
        description="The key the producer filed a Board task under (`task create --source`); empty or absent when none.",
    )
    adr_needed: str | None = Field(
        default=None, description="Why a Board task needs an ADR; empty or absent when it needs none."
    )
    duplicate_search: str | None = Field(
        default=None, description="The queries a Board task's duplicate search ran; empty or absent when none."
    )
    duplicate_resolution: str | None = Field(
        default=None, description="How a Board task's duplicate search resolved its candidates; empty or absent when none."
    )
    follows: str | None = Field(
        default=None, description="The id of the finished task a Board task follows up; empty or absent when none."
    )
    criteria:list[TaskCriterion] | None = Field(
        default=None, description="A Board task's acceptance criteria in file order; absent off the Board."
    )
    definition_of_done: list[TaskCriterion] | None = Field(
        default=None, description="A Board task's Definition of Done items in file order; absent off the Board."
    )
    pause_reason: str | None = Field(
        default=None,
        description="Why a paused Board task waits for a person; empty when it is not paused, absent off the Board.",
    )
    readable: str | None = Field(
        default=None,
        description="The first `readable` guard rule a Board task's description breaks, with its line; empty when it "
        "reads well, absent off the Board.",
    )
    skill: HeldSkill | None = Field(
        default=None, description="The skill machine an In Progress task is held in; absent off the held view."
    )
    interactive: bool | None = Field(
        default=None, description="Whether an accepted take-over made the task interactive; absent off the held view."
    )
    previous: str | None = Field(
        default=None, description="The Board lane the task left on its last move; absent before it has moved."
    )
    moves: dict[str, Move] | None = Field(
        default=None,
        description="The verdict on each Board column the task may move to, by state id; a snapshot keeps it for an active task only.",
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
