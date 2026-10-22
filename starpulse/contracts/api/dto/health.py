"""`/api/analytics/health` and the sessions it draws."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from pydantic import ConfigDict, Field

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.pages import MachineStep


class MachineHistory(_Api):
    """`GET /api/history?task=&machine=`: a task's path on one machine, and how many steps it has taken."""

    task: str
    machine: str
    path: list[MachineStep]
    steps: int


class HealthState(_Api):
    id: str
    name: str
    final: bool
    wip: int
    visits: int | None = None
    mean_s: float | None = None
    max_s: float | None = None
    open: int | None = None


class HealthThroughput(_Api):
    count: int
    per_day: float


# A typed dict, not a model: a window lists thousands of stuck tasks and a model instance each costs more than the
# rest of the read. Its schema is the model's (a comment, not a docstring, so the generated types do not change).
class HealthStuck(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")  # type: ignore[misc]

    task: str
    state: str
    since: float
    dwell_s: float
    counted_to_now: bool


class GapWarning(_Api):
    """The history lost entries between two ids, so any number here may miss some."""

    kind: Literal["gap"]
    stream: str
    after_id: str
    before_id: str
    lost: int
    message: str


class UnknownLaneWarning(_Api):
    """A lane that is no Board state."""

    kind: Literal["unknown_lane"]
    lane: str
    message: str


class Health(_Api):
    """`GET /api/analytics/health`: the Board's flow health over a window."""

    now: float
    window_s: float
    stuck_after_s: float
    states: list[HealthState]
    throughput: HealthThroughput
    stuck: list[HealthStuck]
    warnings: list[Annotated[GapWarning | UnknownLaneWarning, Field(discriminator="kind")]]


class TokenCounts(_Api):
    input: int
    output: int
    cache_read: int
    cache_write: int
    reasoning: int


class SessionHealth(_Api):
    """One harness session's work on one task (`task` None: a branch that names none), from its OTLP signals."""

    harness: str
    session: str
    task: str | None
    kind: Literal["headless", "interactive", "unknown"]
    first_at: float
    last_at: float
    prompts: int
    operator_prompts: int
    prompt_labels: dict[str, int]
    requests: int
    side_requests: int
    tool_calls: int
    tool_failures: int
    tools: dict[str, int]
    rejections: dict[str, int]
    user_rejects: int
    gates: dict[str, int]
    skills: dict[str, int]
    compactions: dict[str, int]
    interrupts: int
    models: list[str]
    efforts: list[str]
    main_model: str | None
    main_effort: str | None
    model_changes: int
    effort_changes: int
    tokens: TokenCounts
    cost_usd: float | None
    agent_s: float
    operator_wait_s: float
    idle_s: float
    steps_before_edit: int | None
    complete: bool


class SliceHealth(_Api):
    """What the sessions that worked one task did together."""

    task: str
    sessions: int
    harnesses: list[str]
    first_at: float
    last_at: float
    models: list[str]
    efforts: list[str]
    steps: int
    side_steps: int
    tool_calls: int
    operator_prompts: int
    prompt_labels: dict[str, int]
    interrupts: int
    rejections: int
    user_rejects: int
    interventions: int
    compactions: int
    skills: dict[str, int]
    escalated: bool
    clean: bool
    tokens: TokenCounts
    cost_usd: float | None
    active_s: float
    operator_wait_s: float
    idle_s: float
    steps_before_edit: int | None
    complete: bool


class Sessions(_Api):
    """`GET /api/analytics/sessions`: session and slice health over a window."""

    now: float
    window_s: float
    sessions: list[SessionHealth]
    slices: list[SliceHealth]


class SessionStep(_Api):
    """One model request of a harness session, with the skill in force when it ran and the calls it made."""

    harness: str
    session: str
    task: str | None
    at: float = Field(description="When the request was logged, in epoch seconds.")
    model: str
    origin: Literal["main", "side", "auxiliary"]
    skill: str = Field(
        description="The skill most recently loaded in the session, counting this step's own; `none` before any."
    )
    activities: list[str] = Field(description="What each call it made performed, in order, with no arguments.")
    keys: list[str] = Field(
        description="One per call: the shell command the instance's redactor left, else the tool's name."
    )
    tokens: TokenCounts
    captured: bool = Field(description="False for a harness the steps-per-completion ledger does not cover (Codex).")


class SessionSteps(_Api):
    """`GET /api/analytics/steps`: every model request of a window, oldest first."""

    now: float
    window_s: float
    steps: list[SessionStep]
