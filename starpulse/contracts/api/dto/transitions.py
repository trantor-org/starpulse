"""The per-task analytics: spend, runs and cost-to-go."""

from pydantic import Field

from starpulse.contracts.api._base import _Api


class SpendPhase(_Api):
    """One phase of one task: the tokens its steps burned, and the task's total against its cell's norm."""

    task: str
    phase: str = Field(description="`claim`, `implement`, `qa`, `deliver` or `review_fix`; see `docs/sources.md`.")
    kind: str | None = Field(description="The task's `kind-*` label, without the prefix; null when it has none.")
    size: int | None = Field(description="The task's `size-*` label; null when it has none.")
    steps: int = Field(description="Model requests, a subagent's included.")
    side_steps: int = Field(description="The subagents' share of `steps`.")
    input: int
    output: int
    cache_read: int
    cache_write: int
    wte: float = Field(description="Uncached input + 1.25 x cache write + 0.1 x cache read + 5 x output.")
    peak_context: int = Field(description="The most input, cache-read and cache-write tokens one request held.")
    compactions: int = Field(description="The compactions that fell in the phase.")
    models: list[str]
    profile: str = Field(
        "", description="`<model>-<effort>` of the phase's first main-thread step, each `unknown` when unrecorded."
    )
    first_at: float
    last_at: float
    task_wte: float = Field(description="`wte` summed over the task's phases.")
    norm_wte: float | None = Field(
        description="The sum of `phase_norm_wte` over the task's phases; null when any is null."
    )
    above_norm: bool = Field(description="`task_wte` is over three times `norm_wte`.")
    phase_norm_wte: float | None = Field(
        description="The median `wte` of this phase over the tasks of the task's kind, size and `profile` that ran it, "
        "or of its kind and size when that profile has under five; null under five."
    )
    norm_profile: str | None = Field(
        description="The `profile` of the cell `phase_norm_wte` came from, or `mixed` for the kind and size cell pooling every profile; "
        "null when there is no norm."
    )
    phase_above_norm: bool = Field(description="`wte` is over three times `phase_norm_wte`.")


class Spend(_Api):
    """The analytics spend route's body: each task's tokens by phase, oldest task first, Codex left out."""

    now: float
    window_s: float
    spend: list[SpendPhase]


class TaskSpend(Spend):
    """`GET /api/task-spend/{id}`: one task's tokens by phase over the window, the rows `Spend` holds for it."""

    task: str


class RunRef(_Api):
    task: str
    steps: int = Field(description="Model requests, a subagent's included.")


class ActivityCount(_Api):
    activity: str
    count: int


class RunDiff(_Api):
    """One transition's reference run against its slowest clean run."""

    kind: str
    size: int
    skill: str
    runs: int = Field(description="Clean completions of the transition.")
    conformant: int = Field(description="Of `runs`, those that conform to the skill's machine.")
    reference: RunRef | None = Field(description="The fewest-step conformant clean run; None when `conformant` is 0.")
    slow: RunRef = Field(description="The most-step clean run.")
    slow_only: list[ActivityCount] = Field(description="Activities the slow run made more often than the reference.")
    reference_only: list[ActivityCount] = Field(
        description="Activities the reference made more often than the slow run."
    )


class RunDiffs(_Api):
    """`GET /api/task-diff/{id}`: a transition with under 5 clean runs reports nothing; one with none that conforms has `conformant` 0."""

    now: float
    window_s: float
    diff: list[RunDiff]


class StateCost(_Api):
    """One skill-machine state's expected cost-to-go within a kind and size."""

    kind: str
    size: int
    skill: str
    state: str = Field(description="A stage of the skill's machine, or `[start]` before its first.")
    n: int = Field(description="The times the state was seen left in the clean completed runs.")
    cost_to_go: float = Field(
        description="The expected agent steps from a run's first step in the state until the run ends."
    )


class CostToGo(_Api):
    """`GET /api/task-cost-to-go/{id}`: every state of each skill machine, whatever its `n`; a consumer holds a cell with a small one."""

    now: float
    window_s: float
    cost_to_go: list[StateCost]


class TaskDiff(RunDiffs):
    """`GET /api/task-diff/{id}`: the task's kind and size, and the rows `RunDiffs` holds for them; no kind or size, no rows."""

    task: str
    kind: str | None
    size: int | None


class TaskCostToGo(CostToGo):
    """`GET /api/task-cost-to-go/{id}`: the task's kind and size, and the rows `CostToGo` holds for them; no kind or size, no rows."""

    task: str
    kind: str | None
    size: int | None
