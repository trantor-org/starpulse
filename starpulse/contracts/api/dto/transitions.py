"""The analytics over transitions, cells, the flow graph, sub-stages, runs and cost."""

from __future__ import annotations

from pydantic import Field

from starpulse.contracts.api._base import _Api


class TransitionCost(_Api):
    """The cost of one skill in force, within one kind and size of task."""

    kind: str = Field(description="The `kind-*` label of the tasks, without the prefix.")
    size: int = Field(description="The `size-*` label of the tasks.")
    skill: str = Field(description="The skill in force on the steps; `none` before any load.")
    tasks: int
    steps: int = Field(description="Model requests, a subagent's included.")
    side_steps: int = Field(description="The subagents' share of `steps`.")
    wasted_steps: int = Field(
        description="Steps with a call that failed, was refused by a guard or hook, or repeats the command before it."
    )
    wasted_rate: float
    agent_s: float = Field(description="The seconds of the steps' requests and tool calls.")
    peak_context: int = Field(description="The most input, cache-read and cache-write tokens one request held.")


class Transitions(_Api):
    """`GET /api/analytics/transitions`: what each skill cost within each kind and size, Codex left out."""

    now: float
    window_s: float
    transitions: list[TransitionCost]


class Cell(_Api):
    """Median steps per clean completion of one kind and size, over its latest-fifth holdout."""

    kind: str
    size: int
    n: int = Field(description="Clean completions in the cell.")
    completions: int = Field(description="Completions in the cell, clean or not.")
    clean_rate: float
    holdout: int = Field(description="The latest fifth of the clean completions by end time, rounded up.")
    median_steps: float = Field(description="Of the holdout's steps, a subagent's included.")
    median_operator_prompts: float = Field(description="Human prompts after the task's claim.")
    median_steps_before_edit: float | None = Field(description="None when no holdout task made an edit.")


class Cells(_Api):
    """`GET /api/analytics/cells`: cells with at least 5 clean completions; a smaller cell reports nothing."""

    now: float
    window_s: float
    cells: list[Cell]


class FlowEdge(_Api):
    """One directly-follows edge of a transition's graph."""

    kind: str
    size: int
    skill: str = Field(description="The skill in force: the transition.")
    source: str = Field(description="An activity, or `[start]`.")
    target: str = Field(description="The activity that directly follows it, or `[end]`.")
    runs: int = Field(description="Runs (tasks) the edge occurred in.")
    count: int = Field(description="Occurrences of the edge.")
    share: float = Field(description="Of the occurrences that leave `source`.")
    cut: bool = Field(description="`source` is a judgement cut: the agent chose there.")


class FlowGraph(_Api):
    """`GET /api/analytics/graph`: the branching directly-follows graph of each transition, Codex left out."""

    now: float
    window_s: float
    graph: list[FlowEdge]


class SubStage(_Api):
    """One stage mined at the judgement cuts of the stretches no skill governs, this week and the week before."""

    kind: str
    size: int
    stage: str = Field(description="The cut that opens the stage, `[start]` for the first.")
    runs: int = Field(description="Runs the stage occurred in over the window; 0 when it did not occur.")
    median_activities: float | None
    previous_runs: int = Field(description="Runs it occurred in over the window before.")
    previous_median_activities: float | None
    stability: float | None = Field(
        description="Of the cell: stages in both windows over stages in either; None when a window mined none."
    )


class SubStages(_Api):
    """`GET /api/analytics/stages`: sub-stages and their stability from one window to the one before."""

    now: float
    window_s: float
    stages: list[SubStage]


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
    """`GET /api/analytics/diff`: a transition with under 5 clean runs reports nothing; one with none that conforms has `conformant` 0."""

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
    """`GET /api/analytics/cost-to-go`: every state of each skill machine, whatever its `n`; a consumer holds a cell with a small one."""

    now: float
    window_s: float
    cost_to_go: list[StateCost]
