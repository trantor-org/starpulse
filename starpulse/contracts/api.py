"""The JSON bodies the HTTP API sends and takes: one pydantic model per body, the page's types generated from them.

`starpulse.api.server` builds every response through these models (`encode`), so a body that drifts from its model is a
500 rather than a page that reads a missing field. Each model is also published as one JSON Schema,
`api.schema.json`, and `web/src/api/types.gen.ts` is generated from that; regenerate both with
`python -m starpulse.contracts.api` and `pnpm --dir starpulse/web run gen:types`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic.json_schema import GenerateJsonSchema

from starpulse.contracts.adapters import ActiveRun, Finding, Move, Pool, RunStatus, Step

__all__ = [
    "BODIES",
    "REQUESTS",
    "RESPONSES",
    "SCHEMA",
    "encode",
    "schema",
]


class _Api(BaseModel):
    """A body of the API: unknown fields are an error, so a producer that adds one must name it here."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- the machines the page draws ---------------------------------------------------------------------------------


class MachineState(_Api):
    id: str
    name: str
    initial: bool
    final: bool


class Transition(_Api):
    source: str
    target: str
    event: str


class Writer(_Api):
    """Who fires a Board event: a runs workflow (by `<instance>/<workflow>` name), `operator` or `agent`."""

    actor: str
    trigger: str


class SubFlow(_Api):
    """Where a Board state opens into another machine, and which Board event each inner final state fires."""

    state: str
    flow: str
    exits: dict[str, str]
    parent: str = Field(description="The flow the link opens under: `board`, or the flow whose `state` it hangs off.")
    when: str = Field(description="What has to hold for the inner flow to run under `state`; empty when always.")


class Launch(_Api):
    """A runs workflow's launch: the skill it starts and the flow that skill draws, null when it has none."""

    skill: str
    flow: str | None


class Machine(_Api):
    source: str | None = Field(
        default=None,
        description='The third party whose events move this machine ("GitHub"); absent for a machine StarPulse\'s own '
        "actors move.",
    )
    states: list[MachineState]
    transitions: list[Transition]
    subflows: list[SubFlow] | None = Field(
        default=None,
        description="The flows that open under this machine's states; the board's first is its In Progress delivery "
        "machine.",
    )
    launches: dict[str, Launch] | None = Field(
        default=None, description="Only the board machine: the skill flow each launching DAG starts."
    )
    writers: dict[str, list[Writer]] | None = Field(default=None, description="Only the board machine: its writers per event.")
    dagActors: list[str] | None = Field(
        default=None, description="Only the board machine: the writers that are runs workflows."
    )
    mainLine: list[str] | None = Field(
        default=None, description="Only the board machine: the state ids along its axis, in order (New to Done)."
    )


class TrailStep(_Api):
    state: str
    event: str
    at: float


class RawAgent(_Api):
    """A Backlog task. On the board its state is its lane; on every other machine, the state its latest machine event left it in."""

    id: str
    title: str
    state: str
    model: str
    labels: list[str] | None = None
    dependencies: list[str] | None = Field(default=None, description="A task's dependencies, as task ids.")
    prs: list[str] | None = Field(default=None, description="A task's pull requests: the PR URLs among its references.")
    task: str | None = Field(default=None, description="A machine's task: the id of the Backlog task its events name.")
    steps: int | None = None
    trail: list[TrailStep] | None = None
    active: float | None = None
    description: str | None = Field(default=None, description="A task's Backlog description.")
    milestone: str | None = Field(default=None, description="A Board task's milestone; empty or absent when it has none.")
    previous: str | None = Field(
        default=None, description="The Board lane the task left on its last move; absent before it has moved."
    )
    moves: dict[str, Move] | None = Field(
        default=None, description="The verdict on each Board column the task may move to, by state id."
    )
    entered: float | None = Field(
        default=None,
        description="When a Board task entered its lane, epoch seconds; absent when the server holds no time for it.",
    )
    created: float | None = Field(
        default=None, description="When a Board task was created, in epoch seconds; null or absent when unknown."
    )
    workable: bool | None = Field(default=None, description="Whether a Board task can be worked now.")
    workable_since: float | None = Field(default=None, description="Since when a workable Board task has been, epoch seconds.")


class Settled(_Api):
    """A task that left the Board's lanes for good: where it settled, when, and the title and assignee it settled with."""

    state: str
    at: float | None
    created: float | None
    title: str
    model: str


class Tie(_Api):
    """Where a lifecycle machine is entered from.

    `declared` is a SubFlow on `machine`'s `state`; `observed` is the state the task held on `machine` when its session
    entered this one; `dag` is a launch by `dag`, which names no machine or state. `count` is the sessions entered
    through it, null for a launch.
    """

    kind: Literal["declared", "observed", "dag"]
    machine: str | None
    state: str | None
    count: int | None
    dag: str | None
    when: str = Field(description="What has to hold for a declared tie to run; empty otherwise.")


class Stuck(_Api):
    """The longest-stuck task of a machine and every machine nested below it: idle over two hours outside a final state."""

    machine: str
    state: str
    since: float = Field(description="When the task last moved, epoch seconds.")


class MachineTies(_Api):
    """What the server derives for a lifecycle machine other than the Board, from every machine's tasks."""

    ties: list[Tie] = Field(description="Leading tie first (declared, then most observed), then DAG launches.")
    parent: str | None = Field(
        description="The machine its leading tie enters it from, else the In Progress machine; null for the In "
        "Progress machine."
    )
    depth: int = Field(description="0 for the In Progress machine, 1 for a machine entered from it, and so on.")
    chain: list[str] = Field(description="The machines above it, outermost first, the In Progress machine left out.")
    nested: list[str] = Field(description="Every machine nested below it.")
    last: float | None = Field(
        description="When a task of this machine or one nested below it last moved, epoch seconds; null with no tasks."
    )
    stuck: Stuck | None


class FlowSnapshot(_Api):
    name: str
    machine: Machine
    agents: list[RawAgent]
    ties: list[Tie] | None = None
    parent: str | None = None
    depth: int | None = None
    chain: list[str] | None = None
    nested: list[str] | None = None
    last: float | None = None
    stuck: Stuck | None = None


# --- the workflows ----------------------------------------------------------------------------------------------


class DagBody(_Api):
    """A runs workflow as the page draws it: the latest run, the runs in flight and the pool it runs on."""

    name: str
    status: RunStatus
    raw: str | None = Field(default=None, description="The engine's own status when it differs from `status`.")
    runId: str
    startedAt: str
    finishedAt: str
    steps: list[Step]
    active: list[ActiveRun] | None = Field(
        default=None, description="Every running or queued run of the workflow, including concurrent ones."
    )
    pool: str | None = Field(default=None, description="The name of the pool the workflow runs on; empty when none.")


class DomainDag(_Api):
    name: str
    runSafe: bool


class Domain(_Api):
    """A domain's DAGs, and whether each is declared safe to run from the page."""

    name: str
    dags: list[DomainDag]


class Cue(_Api):
    """A DAG that runs on the same trigger as a Board event's writer but writes no lane itself."""

    dag: str
    event: str
    state: str
    on: str
    resolves: Literal["forced", "next"] | None = Field(
        default=None,
        description="How a failed run of the DAG clears: `forced` only on a green forced rerun, `next` on the DAG's "
        "next green run.",
    )


class Pull(_Api):
    """One pull request a task cites, as GitHub last answered the server."""

    number: int
    url: str
    checks: Literal["pass", "failing", "pending", "none"] = Field(description="The head commit's check rollup.")
    merged: bool
    merge_sha: str | None = Field(description="The merge commit's SHA; null until the PR merges.")
    merged_at: str | None = Field(description="When the PR merged, ISO 8601 UTC; null until it does.")
    threads: int = Field(description="Unresolved review threads.")
    behind_main: int | None = Field(
        default=None,
        description="Commits `main` holds that the PR's head lacks; null once the head branch is gone."
    )
    stale: bool = Field(description="True when the last read failed and this is the read before it.")


class LedgerRun(_Api):
    """One DAG run a merge row carries: `inferred` when time, not the commit, paired it, and `ambiguous` how many other merges landed in its window."""

    runId: str
    status: RunStatus
    raw: str | None = None
    startedAt: str
    finishedAt: str
    steps: dict[str, RunStatus]
    step: str = Field(description='The step running now, or "".')
    inferred: bool
    ambiguous: int


class LedgerResolved(_Api):
    runId: str
    at: str


class LedgerFail(_Api):
    """A failed run of a cue the merge row holds open: the step it stopped at, and how the failure clears."""

    runId: str
    step: str
    startedAt: str
    finishedAt: str
    resolves: Literal["forced", "next"] | None
    resolved: LedgerResolved | None


class LedgerPull(_Api):
    repo: str
    number: int
    url: str


class LedgerRow(_Api):
    """One merge occurrence: its pull request and commit, the runs paired with it by DAG, and, for another repository's
    merge, the parent merge that pinned it."""

    key: str
    at: float = Field(description="Epoch seconds the merge landed.")
    tasks: list[str]
    sha: str | None = None
    pr: LedgerPull | None = None
    appliedBy: str | None = Field(
        default=None,
        description="The parent merge's key whose pin bump applied this one; null until one has; absent on a merge of "
        "the main repository.",
    )
    applies: list[str] | None = None
    runs: dict[str, LedgerRun]
    fails: dict[str, LedgerFail]
    pinned: bool


class StripBucket(_Api):
    merges: int
    failed: int
    reruns: int


class MergeStrip(_Api):
    """The 24-hour strip of the merge ledger: per bucket, the merges, the failed ones and the forced reruns."""

    since: float
    bucket: float
    buckets: list[StripBucket]


class Capabilities(_Api):
    """What the board writes beyond moves: the page draws Edit, Archive… and New task only for what its board does."""

    edit: bool
    archive: bool
    create: bool | None = None


class Claim(_Api):
    reason: str
    at: float


class MachinePage(_Api):
    """The first page of machines entered from `open`, by name; their bodies are in the snapshot's `flows`."""

    open: str | None
    machines: list[str]
    more: bool


class MachineEntryFrom(_Api):
    machine: str
    state: str


class MachineEntry(_Api):
    at: float
    machine: str
    row: str
    # `from` is a Python keyword.
    origin: MachineEntryFrom | None = Field(alias="from")
    dag: str | None


class MachineStrip(_Api):
    """The last 24 hours of machine entries, counted over every machine."""

    entries: list[MachineEntry]


class Snapshot(_Api):
    graphs: list[str] = Field(description="Every lifecycle machine the server draws, and `runs`.")
    domains: list[Domain] | None = Field(default=None, description="The DAG domains.")
    cues: list[Cue] | None = Field(default=None, description="The DAGs cued by a Board event.")
    boardUrl: str | None = Field(default=None, description="The Backlog board a task links into.")
    hint: str | None = Field(
        default=None,
        description="A Backlog.md project found beside the config while the default board is shown, and how to switch "
        "to it.",
    )
    dags: list[DagBody]
    pools: list[Pool] | None = Field(default=None, description="The concurrency pools the DAGs run on.")
    flows: list[FlowSnapshot]
    machinePage: MachinePage | None = None
    machineStrip: MachineStrip | None = None
    pulls: dict[str, list[Pull]] | None = Field(default=None, description="Each open task's pull requests, by task id.")
    claims: dict[str, Claim] | None = Field(
        default=None,
        description="Each task's latest In Progress claim the board writer refused an agent, and when (epoch seconds).",
    )
    suns: dict[str, float] | None = Field(
        default=None,
        description="Each Board state's share of the lane moves in the week before the last local midnight, which "
        "sizes its sun.",
    )
    ledgers: dict[str, list[LedgerRow]] | None = Field(default=None, description="Each Ledger event's rows, newest first.")
    mergeStrip: MergeStrip | None = None
    mergePins: list[LedgerRow] | None = Field(
        default=None, description="The pinned merge rows of the last day that the newest page leaves out."
    )
    insights: list[Finding] | None = Field(default=None, description="The findings an engine posted that are still live.")
    capabilities: Capabilities | None = Field(
        default=None, description="What the board writes: the task modal draws Edit and Archive only when its board does."
    )
    settled: dict[str, Settled]
    error: str | None
    reading: bool | None = Field(
        default=None,
        description="True while a just-started server is still reading its board: its Board is partial until a "
        "snapshot without it follows.",
    )
    now: float


# --- the event stream: `/api/events` -------------------------------------------------------------------------------


class TaskDelta(_Api):
    """A Board task that moved (`agent` null once it left the lanes)."""

    id: str
    agent: RawAgent | None
    settled: Settled | None


class MoveDelta(_Api):
    """A task a machine event placed on another machine."""

    flow: str
    id: str
    agent: RawAgent


class DagsDelta(_Api):
    """A runs instance's workflows."""

    dags: list[DagBody]
    pools: list[Pool] | None = None
    error: str | None


class PullsDelta(_Api):
    pulls: dict[str, list[Pull]]


class ClaimDelta(_Api):
    task: str
    reason: str
    at: float


class SunsDelta(_Api):
    suns: dict[str, float]


class LedgersDelta(_Api):
    ledgers: dict[str, list[LedgerRow]]
    mergeStrip: MergeStrip | None
    mergePins: list[LedgerRow]


class InsightDelta(_Api):
    """A finding drawn, or retracted when `finding` is null."""

    id: str
    finding: Finding | None


#: Each `/api/events` event name and the model of its `data`.
EVENTS: dict[str, type[BaseModel]] = {
    "snapshot": Snapshot,
    "task": TaskDelta,
    "move": MoveDelta,
    "dags": DagsDelta,
    "pulls": PullsDelta,
    "claim": ClaimDelta,
    "suns": SunsDelta,
    "ledgers": LedgersDelta,
    "insight": InsightDelta,
}


# --- paged and read routes ---------------------------------------------------------------------------------------


class Merges(_Api):
    """`GET /api/merges`: the next page of merge rows, newest first, and whether older ones remain."""

    merges: list[LedgerRow]
    more: bool


class MachineRow(FlowSnapshot):
    """A machine of `GET /api/machines`: whole, with its derivation."""

    ties: list[Tie]
    parent: str | None
    depth: int
    chain: list[str]
    nested: list[str]
    last: float | None
    stuck: Stuck | None


class Machines(_Api):
    """`GET /api/machines`: the next page of machines entered from `open`."""

    open: str | None
    machines: list[MachineRow]
    more: bool


class LaneStep(_Api):
    at: float
    # `from` is a Python keyword.
    origin: str | None = Field(alias="from")
    to: str


class MachineStep(_Api):
    at: float
    event: str
    state: str


class LaneHistory(_Api):
    """`GET /api/history?task=`: a task's lane changes, oldest first."""

    task: str
    path: list[LaneStep]


class RequiredCheck(_Api):
    name: str
    result: Literal["pass", "failing", "pending"]


class PullRecord(_Api):
    """One pull request the PR store read from GitHub, as of `fetchedAt` (epoch seconds)."""

    repo: str
    number: int
    state: Literal["OPEN", "MERGED", "CLOSED"]
    isDraft: bool
    mergeable: str
    baseRefName: str
    headRefOid: str
    body: str
    checks: Literal["pass", "failing", "pending", "none"]
    requiredChecks: list[RequiredCheck]
    threads: int
    updatedAt: str
    fetchedAt: float


class Pulls(_Api):
    """`GET /api/pulls`: the stored pull requests matching every filter given, by repository then number."""

    pulls: list[PullRecord]


class MachineHistory(_Api):
    """`GET /api/history?task=&flow=`: a task's path on one machine, and how many steps it has taken."""

    task: str
    flow: str
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


class LevelTerminal(_Api):
    id: str
    role: str


class LevelOrbitConfig(_Api):
    suns: str
    working: list[str]


class LevelFacet(_Api):
    id: str
    label: str


class LevelActivity(_Api):
    measure: str
    pace: str


class LevelConfig(_Api):
    """What the page needs of the level's config to draw it."""

    title: str
    subject: str
    runs: str
    gates: list[str]
    terminals: list[LevelTerminal]
    orbit: LevelOrbitConfig
    facets: list[LevelFacet]
    activity: LevelActivity


class LevelWip(_Api):
    count: int
    states: dict[str, int]


class LevelStay(_Api):
    id: str
    visits: int
    task_s: float
    mean_s: float | None


class AgingRun(_Api):
    source: str
    task: str
    state: str
    age_s: float
    over: bool


class LevelAging(_Api):
    threshold_s: float | None
    runs: list[AgingRun]


class OrbitTerminal(_Api):
    ended: int


class OrbitWorking(_Api):
    task_s: float


class LevelOrbit(_Api):
    suns: str
    terminals: dict[str, OrbitTerminal]
    working: dict[str, OrbitWorking]


class Arrival(_Api):
    source: str
    state: str
    at: float


class SourceDwell(_Api):
    visits: int
    task_s: float
    mean_s: float | None


class LevelSource(_Api):
    id: str
    shared: bool
    wip: int
    ended: dict[str, int]
    terminal_share: dict[str, float]
    dwell: dict[str, SourceDwell]
    time_share: dict[str, float]


class Level(_Api):
    """`GET /api/level`: the level's flow numbers over a window."""

    now: float
    window_s: float
    history_s: float
    machine: str
    goal: str
    level: LevelConfig
    wip: LevelWip
    throughput: HealthThroughput
    time_in_state: list[LevelStay]
    aging: LevelAging
    orbit: LevelOrbit
    arrivals: list[Arrival]
    sources: list[LevelSource]


class Variant(_Api):
    path: list[str]
    count: int
    share: float


class Norm(_Api):
    path: list[str]
    count: int


class Outlier(_Api):
    source: str
    task: str
    path: list[str]
    distance: int


class ChainState(_Api):
    expected_days: float
    p_goal: float


class Bottleneck(_Api):
    state: str
    path_days: float


class RunGate(_Api):
    gate: str
    crossed: bool
    mandatory: bool
    dominators: list[str]
    post_dominators: list[str]
    witness: list[str] | None


class RunLoop(_Api):
    """One back-edge a run took: its trips and the days they took, from the target's previous visit to each return."""

    # `from` is a Python keyword.
    origin: str = Field(alias="from")
    to: str
    trips: int
    days: float


class TrajectoryRun(_Api):
    source: str
    task: str
    path: list[str]
    reached_goal: bool
    back_edges: int
    sccs: int
    loops: list[RunLoop]
    gates: list[RunGate]


class GateWitness(_Api):
    task: str
    path: list[str]


class GateSummary(_Api):
    gate: str
    runs: int
    crossed: int
    mandatory: int
    bypassed: int
    bypassable: bool
    witness: GateWitness | None


class LevelLoop(_Api):
    """One back-edge across the runs that took it, summed from the runs' own figures."""

    # `from` is a Python keyword.
    origin: str = Field(alias="from")
    to: str
    runs: int
    trips: int
    days: float


class Forecast(_Api):
    """One run still going: where it is, its loops so far, and from its state's row the chance of each terminal and
    of the goal and its expected days to finish, with `n`, the times that row was seen leave. Null with no row."""

    source: str
    task: str
    state: str
    loops: int
    since: float
    p: dict[str, float] | None
    p_goal: float | None
    expected_days: float | None
    n: int
    pooled: bool


class Decile(_Api):
    """One decile of forecast chance of the goal on the held-out runs: its forecasts' mean against the share of
    their runs that reached the goal, null when it holds none."""

    low: float
    high: float
    n: int
    runs: int
    predicted: float | None
    observed: float | None


class Calibration(_Api):
    """The forecast scored on the latest fifth of the ended runs against a chain fitted on the others."""

    fit: int
    held_out: int
    predictions: int
    unscored: int
    deciles: list[Decile]
    calibrated: bool | None


class Trajectories(_Api):
    """`GET /api/level/trajectories`: the paths of the runs that ended in a terminal over a window."""

    now: float
    window_s: float
    history_s: float
    machine: str
    goal: str
    ended: int
    variants: list[Variant]
    norm: Norm | None
    outliers: list[Outlier]
    chain: dict[str, ChainState]
    betweenness: dict[str, float]
    bottleneck: Bottleneck | None
    gates: list[GateSummary]
    loops: list[LevelLoop]
    runs: list[TrajectoryRun]
    forecast: list[Forecast]
    calibration: Calibration


class Change(_Api):
    before: float
    after: float
    change: float


class WhatIf(_Api):
    """`GET /api/level/what-if`: the chain with one transition's probability changed, from the usual first state."""

    now: float
    window_s: float
    history_s: float
    machine: str
    goal: str
    ended: int
    # `from` is a Python keyword.
    origin: str = Field(alias="from")
    to: str
    p: float
    was: float
    n: int
    start: str
    p_goal: Change
    expected_days: Change
    chain: dict[str, ChainState]


class HarnessTier(_Api):
    model: str
    efforts: list[str]


class HarnessBody(_Api):
    name: str
    label: str
    sessions: bool
    reason: str | None
    tiers: dict[str, HarnessTier]


class Harnesses(_Api):
    """`GET /api/harnesses`: the tiers in order and each harness with its models and efforts."""

    tiers: list[str]
    harnesses: list[HarnessBody]


class WindowState(_Api):
    """`/api/history-window`: the effective window, the declared default, and whether Admin's override is in effect."""

    hours: float
    default: float
    overridden: bool


class ForwardedEntry(_Api):
    stream: str
    fields: dict[str, Any]
    kept: list[str] = Field(description="The fields of an entry that stay on the instance.")


class ForwardedField(_Api):
    field: str
    person: bool


class ForwardingUnconfigured(_Api):
    """An instance with no `[forward]` block."""

    configured: Literal[False]


class ForwardingStatus(_Api):
    """What the forwarder would send next, and why."""

    configured: Literal[True]
    url: str
    optIn: bool
    names: bool
    refused: bool
    lastSent: float | None
    problem: str | None
    next: list[ForwardedEntry]
    more: bool
    contract: dict[str, list[ForwardedField]]


class ContractCheck(_Api):
    """One check of the contract between the config and the machines' DAG cues."""

    check: str = Field(description="`cue:<dag>` or `repo:<name>`.")
    status: Literal["pass", "warn", "fail"]
    reason: str


class ContractReport(_Api):
    """The contract checks `starpulse doctor` runs; `ok` is false when any fails."""

    ok: bool
    checks: list[ContractCheck]


class TaskRecord(_Api):
    """`GET /api/task/<id>`: the full record of a task from the board's reader, keyed by its editable fields."""

    task: str
    record: dict[str, Any]


class MilestoneRecord(_Api):
    """A milestone as the board's reader gives it: its sections as text and bullet lists, and its whole description."""

    id: str
    title: str
    outcome: str
    specs: list[str]
    adrs: list[str]
    retro: str
    description: str


class Milestones(_Api):
    """`GET /api/milestones`: every open milestone, by ascending number."""

    milestones: list[MilestoneRecord]


class MilestoneShown(_Api):
    """`GET /api/milestones/<id>`: one open milestone."""

    milestone: MilestoneRecord


class DocSummary(_Api):
    """A doc as the board's lister gives it: its front matter and where it is filed, without its body."""

    id: str
    title: str
    type: str
    created_date: str
    updated_date: str
    path: str


class DocRecord(DocSummary):
    """A doc as the board's reader gives it: the summary and the text after its front matter."""

    body: str


class Docs(_Api):
    """`GET /api/docs`: every open doc, by ascending number."""

    docs: list[DocSummary]


class DocShown(_Api):
    """`GET /api/docs/<id>`: one open doc."""

    doc: DocRecord


# --- writes -----------------------------------------------------------------------------------------------------


class MoveRequest(_Api):
    """`POST /api/move`: move `task` to the column `to`."""

    task: str
    to: str
    actor: str | None = None
    session: str | None = None


class StartRequest(_Api):
    """`POST /api/start`: start a session for `task` on `assignee`."""

    task: str
    assignee: str


class EditRequest(_Api):
    """`POST /api/edit`: change fields of `task`; `base` holds the value each changed field had when the page read it."""

    task: str
    base: dict[str, Any]
    changes: dict[str, Any]
    comment: str | None = None


class ArchiveRequest(_Api):
    """`POST /api/archive`: archive `task`, recording `reason` when it is not blank."""

    task: str
    reason: str | None = None


class CreateRequest(_Api):
    """`POST /api/tasks`: create a task in the board's starting lane."""

    title: str
    description: str | None = None
    priority: str | None = None
    milestone: str | None = None
    assignee: str | None = None
    labels: list[str] | None = None
    dependencies: list[str] | None = None
    acceptanceCriteria: list[str] | None = None


class MilestoneCreateRequest(_Api):
    """`POST /api/milestones`: open a milestone; only the title is required."""

    title: str
    outcome: str | None = None
    specs: list[str] | None = None
    adrs: list[str] | None = None
    retro: str | None = None


class MilestoneEditRequest(_Api):
    """`POST /api/milestones/edit`: replace the `title`, `outcome`, `specs`, `adrs` or `retro` `changes` names."""

    milestone: str
    changes: dict[str, Any]


class MilestoneArchiveRequest(_Api):
    """`POST /api/milestones/archive`: archive `milestone`."""

    milestone: str


class DocCreateRequest(_Api):
    """`POST /api/docs`: file a doc; only the title is required. `type` is `specification`, `guide`, `readme` or `other`."""

    title: str
    type: str | None = None
    folder: str | None = None
    body: str | None = None


class DocEditRequest(_Api):
    """`POST /api/docs/edit`: replace the `title`, `type` or `body` `changes` names."""

    doc: str
    changes: dict[str, Any]


class DocArchiveRequest(_Api):
    """`POST /api/docs/archive`: archive `doc`."""

    doc: str


class WindowRequest(_Api):
    """`PUT /api/history-window`: set the shared history window."""

    hours: float


class ForwardingRequest(_Api):
    """`PUT /api/forwarding`: whether a person's name may leave the instance."""

    opt_in: bool


class RunEventRequest(_Api):
    """`POST /api/runs/events`: one workflow phase a producer reports."""

    phase: str
    workflow: str
    run_id: str
    status: str
    time: float | None = None
    step: str | None = None
    depends: list[str] | None = None


class ForwardedEvent(_Api):
    event_id: str
    stream: str
    fields: dict[str, Any]


class ForwardRequest(_Api):
    """`POST /api/forward`: a batch of events an instance's forwarder sends a hub."""

    opt_in: bool
    events: list[ForwardedEvent]


# --- answers to writes ------------------------------------------------------------------------------------------


class ApiError(_Api):
    """Every refusal: what went wrong."""

    error: str


class SkillRefusal(ApiError):
    """A refusal a skill satisfies: the skill that produces what the guard needs."""

    skill: str


class StaleEdit(ApiError):
    """An edit refused because a field changed since the page read it: those fields with their current values."""

    stale: list[str]
    current: dict[str, Any]


class WindowTooLong(ApiError):
    """A level window longer than the history, with the history's length."""

    history_s: float


class Moved(_Api):
    task: str
    to: str
    advice: str | None = None


class Edited(_Api):
    task: str
    changed: list[str]


class Archived(_Api):
    task: str


class Created(_Api):
    task: str


class MilestoneCreated(_Api):
    milestone: str


class MilestoneEdited(_Api):
    milestone: str
    changed: list[str]


class MilestoneArchived(_Api):
    milestone: str


class DocCreated(_Api):
    doc: str


class DocEdited(_Api):
    doc: str
    changed: list[str]


class DocArchived(_Api):
    doc: str


class Started(_Api):
    task: str
    url: str
    at: float


class RunStarted(_Api):
    runId: str


class Accepted(_Api):
    accepted: bool


class ForwardAccepted(_Api):
    accepted: int
    rejected: int


class InsightPosted(_Api):
    id: str
    replaced: bool


class InsightRetracted(_Api):
    id: str
    retracted: bool


#: Each GET route's `200` body, by path; `/api/task/<id>` by its prefix.
RESPONSES: dict[str, Any] = {
    "/api/snapshot": Snapshot,
    "/api/merges": Merges,
    "/api/machines": Machines,
    "/api/analytics/health": Health,
    "/api/level": Level,
    "/api/level/trajectories": Trajectories,
    "/api/level/what-if": WhatIf,
    "/api/harnesses": Harnesses,
    "/api/history-window": WindowState,
    "/api/doctor": ContractReport,
    "/api/task/": TaskRecord,
    "/api/milestones": Milestones,
    "/api/milestones/": MilestoneShown,
    "/api/docs": Docs,
    "/api/docs/": DocShown,
    "/api/history": LaneHistory | MachineHistory,
    "/api/pulls": Pulls,
    "/api/forwarding": ForwardingStatus | ForwardingUnconfigured,
}

#: Each write route's request body.
REQUESTS: dict[str, type[BaseModel]] = {
    "/api/move": MoveRequest,
    "/api/start": StartRequest,
    "/api/edit": EditRequest,
    "/api/archive": ArchiveRequest,
    "/api/tasks": CreateRequest,
    "/api/milestones": MilestoneCreateRequest,
    "/api/milestones/edit": MilestoneEditRequest,
    "/api/milestones/archive": MilestoneArchiveRequest,
    "/api/docs": DocCreateRequest,
    "/api/docs/edit": DocEditRequest,
    "/api/docs/archive": DocArchiveRequest,
    "/api/history-window": WindowRequest,
    "/api/forwarding": ForwardingRequest,
    "/api/runs/events": RunEventRequest,
    "/api/forward": ForwardRequest,
    "/api/insights": Finding,
}

#: Every body a route may send, by route: what `encode` validates a body against.
BODIES: dict[str, Any] = {
    "error": ApiError,
    "snapshot": Snapshot,
    "merges": Merges | ApiError,
    "machines": Machines | ApiError,
    "history": LaneHistory | MachineHistory | ApiError,
    "pulls": Pulls | ApiError,
    "health": Health | ApiError,
    "level": Level | ApiError | WindowTooLong,
    "trajectories": Trajectories | ApiError | WindowTooLong,
    "what_if": WhatIf | ApiError | WindowTooLong,
    "harnesses": Harnesses,
    "window": WindowState | ApiError,
    "forwarding": ForwardingStatus | ForwardingUnconfigured | ApiError,
    "doctor": ContractReport,
    "task": TaskRecord | ApiError,
    "move": Moved | SkillRefusal | ApiError,
    "start": Started | SkillRefusal | ApiError,
    "edit": Edited | StaleEdit | SkillRefusal | ApiError,
    "archive": Archived | SkillRefusal | ApiError,
    "create": Created | SkillRefusal | ApiError,
    "milestones": Milestones | ApiError,
    "milestone": MilestoneShown | ApiError,
    "milestone_create": MilestoneCreated | SkillRefusal | ApiError,
    "milestone_edit": MilestoneEdited | SkillRefusal | ApiError,
    "milestone_archive": MilestoneArchived | SkillRefusal | ApiError,
    "docs": Docs | ApiError,
    "doc": DocShown | ApiError,
    "doc_create": DocCreated | SkillRefusal | ApiError,
    "doc_edit": DocEdited | SkillRefusal | ApiError,
    "doc_archive": DocArchived | SkillRefusal | ApiError,
    "run": RunStarted | ApiError,
    "ingest": Accepted | ApiError,
    "forward": ForwardAccepted | ApiError,
    "insight": InsightPosted | InsightRetracted | ApiError,
}

_ADAPTERS: dict[int, TypeAdapter[Any]] = {}


def encode(kind: str, data: Any) -> bytes:
    """The JSON bytes of `data` as the route `kind` may send it, raising `ValidationError` for a body no model of
    `BODIES[kind]` accepts; the page reads only fields a model names."""
    annotation = BODIES[kind]
    if (adapter := _ADAPTERS.get(id(annotation))) is None:  # built once: building one costs more than a small body
        adapter = _ADAPTERS[id(annotation)] = TypeAdapter(annotation)
    return adapter.dump_json(adapter.validate_python(data), by_alias=True, exclude_unset=True)


def event(name: str, data: Any) -> str:
    """The JSON text of the `data` of `/api/events`' event `name`, raising `ValidationError` for one its model refuses."""
    model = EVENTS[name]
    return model.model_validate(data).model_dump_json(by_alias=True, exclude_unset=True)


class ApiContract(_Api):
    """The root of `api.schema.json`: every body as a property, so the generated types name each one."""

    snapshot: Snapshot
    events: list[
        TaskDelta | MoveDelta | DagsDelta | PullsDelta | ClaimDelta | SunsDelta | LedgersDelta | InsightDelta
    ]
    merges: Merges
    machines: Machines
    laneHistory: LaneHistory
    machineHistory: MachineHistory
    pulls: Pulls
    health: Health
    level: Level
    trajectories: Trajectories
    whatIf: WhatIf
    harnesses: Harnesses
    windowState: WindowState
    forwardingStatus: ForwardingStatus
    forwardingUnconfigured: ForwardingUnconfigured
    contractReport: ContractReport
    taskRecord: TaskRecord
    milestones: Milestones
    milestoneShown: MilestoneShown
    docs: Docs
    docShown: DocShown
    requests: list[
        MoveRequest
        | StartRequest
        | EditRequest
        | ArchiveRequest
        | CreateRequest
        | MilestoneCreateRequest
        | MilestoneEditRequest
        | MilestoneArchiveRequest
        | DocCreateRequest
        | DocEditRequest
        | DocArchiveRequest
        | WindowRequest
        | ForwardingRequest
        | RunEventRequest
        | ForwardRequest
    ]
    answers: list[
        Moved
        | Edited
        | Archived
        | Created
        | MilestoneCreated
        | MilestoneEdited
        | MilestoneArchived
        | DocCreated
        | DocEdited
        | DocArchived
        | Started
        | RunStarted
        | Accepted
        | ForwardAccepted
        | InsightPosted
        | InsightRetracted
        | ApiError
        | SkillRefusal
        | StaleEdit
        | WindowTooLong
    ]


#: Where the schema is written: beside `machine.schema.json`, not among the adapter contracts' `schemas/`, which ship.
SCHEMA = Path(__file__).parent.parent / "api.schema.json"


class _Generator(GenerateJsonSchema):
    """Titles only models: a field title would make json-schema-to-typescript name a type for each field."""

    def field_title_should_be_set(self, schema: Any) -> bool:
        return False


def schema() -> str:
    """The JSON Schema of every body, as the file `SCHEMA` holds it."""
    document = ApiContract.model_json_schema(by_alias=True, schema_generator=_Generator)
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    SCHEMA.write_text(schema())
