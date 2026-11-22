"""The history a task carries, and the session and slice health `starpulse.sessions` returns."""

from typing import Literal

from pydantic import Field

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.pages import MachineStep


class MachineHistory(_Api):
    """`GET /api/history?task=&machine=`: a task's path on one machine, and how many steps it has taken."""

    task: str
    machine: str
    path: list[MachineStep]
    steps: int


class MachineEvent(_Api):
    at: float
    machine: str
    event: str
    # `from` is a Python keyword.
    origin: str = Field(alias="from")
    to: str


class TaskEventHistory(_Api):
    """`GET /api/history?task=&hours=`: every machine event of a task in the window, oldest first."""

    task: str
    hours: float
    events: list[MachineEvent]


# A typed dict, not a model: a window lists thousands of stuck tasks and a model instance each costs more than the
# rest of the read. Its schema is the model's (a comment, not a docstring, so the generated types do not change).


class TokenCounts(_Api):
    input: int
    output: int
    cache_read: int
    cache_write: int
    reasoning: int


class AgentSpend(TokenCounts):
    subagents: int = Field(0, description="The subagents of this type whose requests named their instance id.")
    first_request_cache_write: int = Field(0, description="The cache_write of each such subagent's first request, summed.")


class SessionHealth(_Api):
    """One harness session's work on one task (`task` None: a branch that names none), from its OTLP signals."""

    harness: str
    session: str
    task: str | None
    kind: Literal["headless", "interactive", "unknown"]
    eval: str
    origin: str
    entrypoint: str = Field(
        description="The launch's `claude_code.entrypoint` resource attribute (`cli`, `sdk-cli`); empty when it set none."
    )
    first_request_tokens: int | None = Field(
        description="The prompt tokens (input, cache read and cache write) of the session's first main-thread request that sent any; None when it made none."
    )
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
    raises: int
    lowers: int
    tokens: TokenCounts
    agents: dict[str, AgentSpend] = Field(
        description="Each subagent type's token totals among `tokens` (`qa-<lens>` for a qa lens); only a subagent that names its type."
    )
    role: str = Field(
        description="The furthest phase skill (`starting-task`, `tdd`, `qa`, `deliver`, `fix-checks`, `review-fix`, `verify`) the session loaded on this task; `other` when it loaded none."
    )
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
    raises: int
    lowers: int
    escalated: bool
    clean: bool
    tokens: TokenCounts
    cost_usd: float | None
    active_s: float
    operator_wait_s: float
    idle_s: float
    steps_before_edit: int | None
    complete: bool


