"""The per-task analytics: spend."""

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
    no_norm_reason: str | None = Field(
        description="Why `phase_norm_wte` is null: `batch umbrella`, `no kind or size`, or `under 5 peers in kind × size`; "
        "null when there is a norm."
    )
    phase_above_norm: bool = Field(description="`wte` is over three times `phase_norm_wte`.")


class Spend(_Api):
    """The analytics spend route's body: each task's tokens by phase, oldest task first."""

    now: float
    window_s: float
    spend: list[SpendPhase]
