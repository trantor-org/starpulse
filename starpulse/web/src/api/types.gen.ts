/* Generated from starpulse/schemas/api.schema.json by pnpm run gen:types; edit starpulse/contracts/api/, not this file. */

/**
 * The root of `api.schema.json`: every body as a property, so the generated types name each one.
 */
export interface ApiContract {
  answers: (
    | Moved
    | MovedEach
    | Edited
    | Archived
    | ArchivedEach
    | Judged
    | Rated
    | Restored
    | Retired
    | TakenOver
    | RetiredImported
    | Completed
    | Claimed
    | Parked
    | Reviewed
    | Created
    | CreatedEach
    | MilestoneCreated
    | MilestoneEdited
    | MilestoneArchived
    | DocCreated
    | DocEdited
    | DocArchived
    | DocRestored
    | Started
    | RunStarted
    | Accepted
    | ApiError
    | SkillRefusal
    | StaleEdit
    | WindowTooLong
  )[];
  build: BuildEvent;
  cells: Cells;
  contractReport: ContractReport;
  costToGo: CostToGo;
  diff: RunDiffs;
  docShown: DocShown;
  docs: Docs;
  donePage: DonePage;
  events: (
    TaskDelta | MoveDelta | DagsDelta | PullsDelta | ClaimDelta | VerdictDelta | LedgersDelta | SchedulerStatus
  )[];
  graph: FlowGraph;
  harnesses: Harnesses;
  health: Health;
  laneHistory: LaneHistory;
  ledger: LedgerPage;
  ledgerChange: LedgerChange;
  machineHistory: MachineHistory;
  machines: Machines;
  milestoneShown: MilestoneShown;
  milestones: Milestones;
  missedLoads: MissedLoads;
  pulls: Pulls;
  requests: (
    | MoveRequest
    | StartRequest
    | EditRequest
    | ArchiveRequest
    | VerdictRequest
    | RatingRequest
    | MissRequest
    | RestoreRequest
    | RetireRequest
    | TakeOverRequest
    | RetiredImportRequest
    | CompleteRequest
    | ClaimRequest
    | ParkRequest
    | ReviewRequest
    | CreateRequest
    | MilestoneCreateRequest
    | MilestoneEditRequest
    | MilestoneArchiveRequest
    | DocCreateRequest
    | DocEditRequest
    | DocArchiveRequest
    | DocRestoreRequest
    | WindowRequest
    | SchedulerRequest
  )[];
  restarting: RestartingEvent;
  retiredTasks: RetiredTasks;
  schedulerStatus: SchedulerStatus;
  searchResults: SearchResults;
  sessionSteps: SessionSteps;
  sessions: Sessions;
  snapshot: Snapshot;
  stages: SubStages;
  taskEventHistory: TaskEventHistory;
  taskRecord: TaskRecord;
  traceClusters: TraceClusters;
  trajectories: Trajectories;
  transitions: Transitions;
  windowState: WindowState;
}
/**
 * A move's answer. The operator's move of an unheld task into the working state also starts its session: `url`
 * opens it, or `startError` says why none started.
 */
export interface Moved {
  advice?: string | null;
  startError?: string | null;
  task: string;
  to: string;
  url?: string | null;
}
/**
 * A batch move's answer: the tasks it moved, and each refused task with why.
 */
export interface MovedEach {
  moved: string[];
  refused: {
    [k: string]: string;
  };
}
export interface Edited {
  changed: string[];
  task: string;
}
export interface Archived {
  task: string;
}
/**
 * A batch archive's answer: the tasks it archived, and each refused task with why.
 */
export interface ArchivedEach {
  archived: string[];
  refused: {
    [k: string]: string;
  };
}
export interface Judged {
  check: string;
  fix?: string | null;
  task: string;
  verdict: string;
}
export interface Rated {
  changes: number;
  reason: string;
  task: string;
  verdict: string;
}
export interface Restored {
  task: string;
}
export interface Retired {
  task: string;
}
export interface TakenOver {
  task: string;
}
export interface RetiredImported {
  task: string;
}
export interface Completed {
  task: string;
}
export interface Claimed {
  assignee: string;
  task: string;
  to: string;
}
export interface Parked {
  task: string;
  to: string;
}
export interface Reviewed {
  task: string;
  to: string;
}
export interface Created {
  task: string;
}
/**
 * A batch create's answer: each spec's new task, or why it was refused, in the order the specs came.
 */
export interface CreatedEach {
  results: (Created | SkillRefusal | ApiError)[];
}
/**
 * A refusal a skill satisfies: the skill that produces what the guard needs.
 */
export interface SkillRefusal {
  error: string;
  skill: string;
}
/**
 * Every refusal: what went wrong.
 */
export interface ApiError {
  error: string;
}
export interface MilestoneCreated {
  milestone: string;
}
export interface MilestoneEdited {
  changed: string[];
  milestone: string;
}
export interface MilestoneArchived {
  milestone: string;
}
export interface DocCreated {
  doc: string;
}
export interface DocEdited {
  changed: string[];
  doc: string;
}
export interface DocArchived {
  doc: string;
}
export interface DocRestored {
  doc: string;
}
export interface Started {
  at: number;
  task: string;
  url: string;
}
export interface RunStarted {
  runId: string;
}
export interface Accepted {
  accepted: boolean;
  deprecated?: string | null;
}
/**
 * An edit refused because a field changed since the page read it: those fields with their current values.
 */
export interface StaleEdit {
  current: {
    [k: string]: unknown;
  };
  error: string;
  stale: string[];
}
/**
 * A level or telemetry window longer than its history, with the history's length.
 */
export interface WindowTooLong {
  error: string;
  history_s: number;
}
/**
 * The page build the server serves, sent right after each connect's snapshot: a hash of the built page's `index.html`,
 * which names every chunk it loads by its digest. A page that holds another build than the one it is named is out of date.
 */
export interface BuildEvent {
  id: string;
}
/**
 * `GET /api/analytics/cells`: cells with at least 5 clean completions; a smaller cell reports nothing.
 */
export interface Cells {
  cells: Cell[];
  now: number;
  window_s: number;
}
/**
 * Median steps per clean completion of one kind and size, over its latest-fifth holdout.
 */
export interface Cell {
  clean_rate: number;
  /**
   * Completions in the cell, clean or not.
   */
  completions: number;
  /**
   * The latest fifth of the clean completions by end time, rounded up.
   */
  holdout: number;
  kind: string;
  /**
   * Human prompts after the task's claim.
   */
  median_operator_prompts: number;
  /**
   * Of the holdout's steps, a subagent's included.
   */
  median_steps: number;
  /**
   * None when no holdout task made an edit.
   */
  median_steps_before_edit: number | null;
  /**
   * Clean completions in the cell.
   */
  n: number;
  size: number;
}
/**
 * The contract checks `starpulse doctor` runs; `ok` is false when any fails.
 */
export interface ContractReport {
  checks: ContractCheck[];
  ok: boolean;
}
/**
 * One check of the contract between the config and the machines' DAG cues.
 */
export interface ContractCheck {
  /**
   * `cue:<dag>` or `repo:<name>`.
   */
  check: string;
  reason: string;
  status: "pass" | "warn" | "fail";
}
/**
 * `GET /api/analytics/cost-to-go`: every state of each skill machine, whatever its `n`; a consumer holds a cell with a small one.
 */
export interface CostToGo {
  cost_to_go: StateCost[];
  now: number;
  window_s: number;
}
/**
 * One skill-machine state's expected cost-to-go within a kind and size.
 */
export interface StateCost {
  /**
   * The expected agent steps from a run's first step in the state until the run ends.
   */
  cost_to_go: number;
  kind: string;
  /**
   * The times the state was seen left in the clean completed runs.
   */
  n: number;
  size: number;
  skill: string;
  /**
   * A stage of the skill's machine, or `[start]` before its first.
   */
  state: string;
}
/**
 * `GET /api/analytics/diff`: a transition with under 5 clean runs reports nothing; one with none that conforms has `conformant` 0.
 */
export interface RunDiffs {
  diff: RunDiff[];
  now: number;
  window_s: number;
}
/**
 * One transition's reference run against its slowest clean run.
 */
export interface RunDiff {
  /**
   * Of `runs`, those that conform to the skill's machine.
   */
  conformant: number;
  kind: string;
  /**
   * The fewest-step conformant clean run; None when `conformant` is 0.
   */
  reference: RunRef | null;
  /**
   * Activities the reference made more often than the slow run.
   */
  reference_only: ActivityCount[];
  /**
   * Clean completions of the transition.
   */
  runs: number;
  size: number;
  skill: string;
  slow: RunRef1;
  /**
   * Activities the slow run made more often than the reference.
   */
  slow_only: ActivityCount[];
}
export interface RunRef {
  /**
   * Model requests, a subagent's included.
   */
  steps: number;
  task: string;
}
export interface ActivityCount {
  activity: string;
  count: number;
}
/**
 * The most-step clean run.
 */
export interface RunRef1 {
  /**
   * Model requests, a subagent's included.
   */
  steps: number;
  task: string;
}
/**
 * `GET /api/docs/<id>`: one open doc.
 */
export interface DocShown {
  doc: DocRecord;
}
/**
 * A doc as the board's reader gives it: the summary and the text after its front matter.
 */
export interface DocRecord {
  body: string;
  created_date: string;
  id: string;
  path: string;
  title: string;
  type: string;
  updated_date: string;
}
/**
 * `GET /api/docs`: every open doc, by ascending number.
 */
export interface Docs {
  docs: DocSummary[];
}
/**
 * A doc as the board's lister gives it: its front matter and where it is filed, without its body.
 */
export interface DocSummary {
  created_date: string;
  id: string;
  path: string;
  title: string;
  type: string;
  updated_date: string;
}
/**
 * `GET /api/done`: the next page of done tasks past their hot day, newest first, and whether older ones remain.
 */
export interface DonePage {
  more: boolean;
  tasks: RawTask[];
}
/**
 * A Backlog task. On the board its state is its lane; on every other machine, the state its latest machine event left it in.
 */
export interface RawTask {
  active?: number | null;
  /**
   * The session that last claimed a Board task; empty when none has, absent off the Board.
   */
  assignee?: string | null;
  /**
   * When a held Board task's claim expires, its last renewal plus the claim TTL, epoch seconds; null when unheld, not In Progress, or before the first sweep pass.
   */
  claim_expires_at?: number | null;
  /**
   * When a Board task was created, in epoch seconds; null or absent when unknown.
   */
  created?: number | null;
  /**
   * A Board task's acceptance criteria in file order; absent off the Board.
   */
  criteria?: TaskCriterion[] | null;
  /**
   * A task's dependencies, as task ids.
   */
  dependencies?: string[] | null;
  /**
   * A task's Backlog description.
   */
  description?: string | null;
  /**
   * When a Board task entered its lane, epoch seconds; absent when the server holds no time for it.
   */
  entered?: number | null;
  id: string;
  /**
   * A Board task's Impact (low, medium or high); empty or absent when it has none.
   */
  impact?: string | null;
  /**
   * Whether an accepted take-over made the task interactive; absent off the held view.
   */
  interactive?: boolean | null;
  labels?: string[] | null;
  /**
   * A Board task's milestone; empty or absent when it has none.
   */
  milestone?: string | null;
  model: string;
  /**
   * A snapshot's key into its `move_sets` for the task's `moves`; absent when it has none.
   */
  move_set?: string | null;
  /**
   * The verdict on each Board column the task may move to, by state id; a snapshot names the set in `move_set` instead, and a delta carries it here.
   */
  moves?: {
    [k: string]: Move;
  } | null;
  /**
   * Why a paused Board task waits for a person; empty when it is not paused, absent off the Board.
   */
  pause_reason?: string | null;
  /**
   * The Board lane the task left on its last move; absent before it has moved.
   */
  previous?: string | null;
  /**
   * The agent profile a Board task is routed to; empty when none, absent off the Board.
   */
  profile?: string | null;
  /**
   * A task's pull requests: the PR URLs among its references.
   */
  prs?: string[] | null;
  /**
   * The claim-TTL release a Board task's claim ended in; null when none ended it.
   */
  released?: ClaimRelease | null;
  /**
   * A task's scheduler runs: those whose run id names it (`dag-run-task-<N>-<ts>`).
   */
  runs?: TaskRun[] | null;
  /**
   * The skill machine an In Progress task is held in; absent off the held view.
   */
  skill?: HeldSkill | null;
  state: string;
  steps?: number | null;
  /**
   * A machine's task: the id of the Backlog task its events name.
   */
  task?: string | null;
  title: string;
  trail?: TrailStep[] | null;
  /**
   * A Board task's type; empty or absent when it has none.
   */
  type?: string | null;
  /**
   * A Board task's Urgency (low, medium or high); empty or absent when it has none.
   */
  urgency?: string | null;
  /**
   * Whether a Board task can be worked now.
   */
  workable?: boolean | null;
  /**
   * Since when a workable Board task has been, epoch seconds.
   */
  workable_since?: number | null;
}
/**
 * One acceptance criterion of a Board task and whether it is checked.
 */
export interface TaskCriterion {
  checked: boolean;
  text: string;
}
/**
 * The verdict on moving a task to one column: allowed, or guarded by a declared rule.
 */
export interface Move {
  /**
   * The verdict for an actor a guard treats apart from the rest, such as one it exempts, by actor; any other actor meets the move's own.
   */
  actors?: {
    [k: string]: Verdict;
  };
  /**
   * False when a guard the board writer enforces would refuse the move.
   */
  allowed: boolean;
  /**
   * What the refusing guard needs; empty when the move is allowed.
   */
  reason?: string;
  /**
   * The skill that produces what the guard needs; empty when allowed.
   */
  skill?: string;
  /**
   * The actors the machine YAML declares for the event behind the move; empty when it declares none, and then any actor may make it.
   */
  writers?: string[];
}
/**
 * What a guard says to one actor about a move: allowed, or the reason and skill of the rule that refuses it.
 */
export interface Verdict {
  /**
   * False when a guard would refuse the move to this actor.
   */
  allowed: boolean;
  /**
   * What the refusing guard needs; empty when allowed.
   */
  reason?: string;
  /**
   * The skill that produces what the guard needs; empty when allowed.
   */
  skill?: string;
}
/**
 * The claim a Board task's claim-TTL sweep released: when, and the session, last renewal and TTL it released.
 */
export interface ClaimRelease {
  /**
   * When the release was recorded, epoch seconds.
   */
  at: number;
  /**
   * The session's last renewal before the release, epoch seconds.
   */
  last_renewal: number;
  session: string;
  /**
   * The claim TTL, in seconds, the session missed.
   */
  ttl: number;
}
/**
 * One scheduler run a task's id names, linked to the run's own page.
 */
export interface TaskRun {
  startedAt: string;
  status: string;
  url: string;
}
export interface HeldSkill {
  /**
   * The state the task holds in the skill machine.
   */
  current?: string | null;
  /**
   * The skill machine the task is in.
   */
  name: string;
  /**
   * The edge the skill declares; null when none is declared.
   */
  next?: HeldNext | null;
  /**
   * The skill machine's state ids, in declared order.
   */
  states: string[];
}
export interface HeldNext {
  /**
   * Whether the next edge runs a skill or an operation.
   */
  kind: "skill" | "operation";
  /**
   * The skill or operation the edge hands to.
   */
  name: string;
}
export interface TrailStep {
  at: number;
  event: string;
  state: string;
}
/**
 * A Board task that moved (`agent` null once it left the lanes).
 */
export interface TaskDelta {
  agent: RawTask | null;
  id: string;
  settled: Settled | null;
}
/**
 * A task that left the Board's lanes for good: where it settled, when, and the title, assignee, milestone and labels it settled with.
 */
export interface Settled {
  at: number | null;
  created: number | null;
  /**
   * The labels it settled with.
   */
  labels?: string[];
  /**
   * The milestone it settled in; empty when it had none.
   */
  milestone?: string;
  model: string;
  state: string;
  title: string;
}
/**
 * A task a machine event placed on another machine.
 */
export interface MoveDelta {
  agent: RawTask;
  id: string;
  machine: string;
}
/**
 * A runs instance's workflows.
 */
export interface DagsDelta {
  cpu?: {
    [k: string]: Cpu;
  } | null;
  dags: DagBody[];
  error: string | null;
  pools?: Pool[] | null;
}
/**
 * The share of the host's CPU an instance's scheduler and workers used since the last reading.
 */
export interface Cpu {
  /**
   * How many cores the host has.
   */
  cores: number;
  /**
   * Their CPU time over all the host's cores, from 0 to 1.
   */
  share: number;
}
/**
 * A runs workflow as the page draws it: the latest run, the runs in flight and the pool it runs on.
 */
export interface DagBody {
  /**
   * Every running or queued run of the workflow, including concurrent ones.
   */
  active?: ActiveRun[] | null;
  finishedAt: string;
  name: string;
  /**
   * The name of the pool the workflow runs on; empty when none.
   */
  pool?: string | null;
  /**
   * The engine's own status when it differs from `status`.
   */
  raw?: string | null;
  /**
   * What the workflow declares about a rerun repeating its effects; None when it declares nothing.
   */
  rerun: Rerun | null;
  runId: string;
  /**
   * The cron expressions that start the workflow; empty when it runs only when asked for.
   */
  schedule: string[];
  startedAt: string;
  /**
   * The workflow's runs over the last seven days; None when it never ran or they are unknown.
   */
  stats: RunStats | null;
  status: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
  steps: Step[];
}
/**
 * One run of a DAG that is running or queued now.
 */
export interface ActiveRun {
  /**
   * The engine's own status for the run when it differs from `status`, shown as is.
   */
  raw?: string | null;
  /**
   * The run's id.
   */
  runId: string;
  /**
   * When the run started, or was queued while it waits, ISO 8601 UTC (`2026-10-02T17:00:00Z`).
   */
  startedAt: string;
  /**
   * The run's status: `running` or `queued`.
   */
  status: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
  /**
   * The step the run entered last among those running; empty while it is queued or between steps.
   */
  step: string;
  /**
   * When the run entered `step`, ISO 8601 UTC; empty when `step` is.
   */
  stepStartedAt: string;
  /**
   * Each of the DAG's steps by name with its status in this run.
   */
  steps: {
    [k: string]: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
  };
}
/**
 * What a DAG declares about a rerun of it: safe (all None), once per `key`, or repeating its effects.
 */
export interface Rerun {
  /**
   * What the DAG keys its effects by, so a rerun for the same key repeats none; None when it declares no key.
   */
  key: string | null;
  /**
   * Why a rerun repeats the DAG's effects; None when the DAG declares it does not.
   */
  repeats: string | null;
  /**
   * The step whose effects repeat; None when the DAG names none.
   */
  step: string | null;
}
/**
 * A DAG's runs over the last seven days.
 */
export interface RunStats {
  /**
   * The share of those runs that failed; None while none is over.
   */
  failureShare: number | null;
  /**
   * The summed duration of the window's runs that are over, in hours.
   */
  hours: number;
  /**
   * The median duration of those runs; None while none is over.
   */
  medianSeconds: number | null;
  /**
   * The 95th-percentile duration of those runs; None while none is over.
   */
  p95Seconds: number | null;
  /**
   * The runs that began in the window, over or not.
   */
  runs: number;
}
/**
 * One step of a DAG in its latest run.
 */
export interface Step {
  /**
   * Names of the steps that must finish before this one starts.
   */
  depends: string[];
  /**
   * The phase kind the step declares (`agent`), or None when it declares none.
   */
  kind: string | null;
  /**
   * The step's outcomes in the runs that are over, newest first, at most five; empty when the scheduler keeps none or the step never ran.
   *
   * @maxItems 5
   */
  last:
    | []
    | ["not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped"]
    | [
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped"
      ]
    | [
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped"
      ]
    | [
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped"
      ]
    | [
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped",
        "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped"
      ];
  /**
   * The lock the step takes so no other holder runs at once; None when it declares none or the scheduler has no lock to declare.
   */
  lock: string | null;
  /**
   * The step's name, unique within its DAG.
   */
  name: string;
  /**
   * What must hold for the step to run, as the scheduler states it; None when it declares none.
   */
  precondition: string | null;
  /**
   * The engine's own status for the step when it differs from `status`, shown as is.
   */
  raw?: string | null;
  /**
   * The step's status in the latest run.
   */
  status: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
}
/**
 * One concurrency pool: the cap on the runs that may execute at once, and the runs holding or awaiting it.
 */
export interface Pool {
  /**
   * The most runs the pool lets execute at once.
   */
  cap: number;
  /**
   * The pool's name, unique on its scheduler; a DAG's `pool` names it.
   */
  name: string;
  /**
   * The runs waiting for the pool to have room.
   */
  queued: number;
  /**
   * The runs executing on the pool now.
   */
  running: number;
}
export interface PullsDelta {
  pulls: {
    [k: string]: Pull[];
  };
}
/**
 * One pull request a task cites, as GitHub last answered the server.
 */
export interface Pull {
  /**
   * Commits `main` holds that the PR's head lacks; null once the head branch is gone.
   */
  behind_main?: number | null;
  /**
   * The head commit's check rollup.
   */
  checks: "pass" | "failing" | "pending" | "none";
  /**
   * The PR closed without merging.
   */
  closed?: boolean;
  /**
   * The open PR conflicts with its base branch.
   */
  conflicting?: boolean;
  /**
   * The merge commit's SHA; null until the PR merges.
   */
  merge_sha: string | null;
  merged: boolean;
  /**
   * When the PR merged, ISO 8601 UTC; null until it does.
   */
  merged_at: string | null;
  number: number;
  /**
   * The `org/repo` the PR belongs to; a number alone repeats across repositories.
   */
  repo: string;
  /**
   * Always false: nothing polls GitHub, so a record is current until a newer event lands.
   */
  stale: boolean;
  /**
   * Unresolved review threads.
   */
  threads: number;
  url: string;
}
export interface ClaimDelta {
  at: number;
  reason: string;
  task: string;
}
/**
 * One qa lens's verdict on a task, as the ingest took it.
 */
export interface VerdictDelta {
  at: number;
  lens: string;
  outcome: "PASS" | "CHANGES";
  reason: string;
  round: number;
  task: string;
}
/**
 * The merge strip and pins since the last event, whole. A Ledger's rows are not here: a page that has one open
 * reads `GET /api/ledger/<event>/events`.
 */
export interface LedgersDelta {
  mergePins: LedgerRow[];
  mergeStrip: MergeStrip | null;
}
/**
 * One merge occurrence: its pull request and commit, the runs paired with it by DAG, and, for another repository's
 * merge, the parent merge that pinned it.
 */
export interface LedgerRow {
  /**
   * The parent merge's key whose pin bump applied this one; null until one has; absent on a merge of the main repository.
   */
  appliedBy?: string | null;
  applies?: string[] | null;
  /**
   * Epoch seconds the merge landed.
   */
  at: number;
  fails: {
    [k: string]: LedgerFail;
  };
  key: string;
  pinned: boolean;
  pr?: LedgerPull | null;
  runs: {
    [k: string]: LedgerRun;
  };
  sha?: string | null;
  tasks: string[];
}
/**
 * A failed run of a cue the merge row holds open: the step it stopped at, and how the failure clears.
 */
export interface LedgerFail {
  finishedAt: string;
  resolved: LedgerResolved | null;
  resolves: ("forced" | "next") | null;
  runId: string;
  startedAt: string;
  step: string;
}
export interface LedgerResolved {
  at: string;
  runId: string;
}
export interface LedgerPull {
  number: number;
  repo: string;
  url: string;
}
/**
 * One DAG run a merge row carries: `inferred` when time, not the commit, paired it, and `ambiguous` how many other merges landed in its window.
 */
export interface LedgerRun {
  ambiguous: number;
  finishedAt: string;
  inferred: boolean;
  raw?: string | null;
  runId: string;
  startedAt: string;
  status: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
  /**
   * The step running now, or "".
   */
  step: string;
  steps: {
    [k: string]: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
  };
}
/**
 * The 24-hour strip of the merge ledger: per bucket, the merges, the failed ones and the forced reruns.
 */
export interface MergeStrip {
  bucket: number;
  buckets: StripBucket[];
  since: number;
}
export interface StripBucket {
  failed: number;
  merges: number;
  reruns: number;
}
/**
 * Whether the scheduler admits tasks, and the capacity strip's readings; no dimensions before the first sample.
 *
 * `inFlight`, `next`, `sessionsByHarness` and `needsOperator` are served only by a server that runs a dispatch loop; without one they
 * are absent.
 */
export interface SchedulerStatus {
  dimensions: SchedulerDimension[];
  enabled: boolean;
  /**
   * The harness the loop starts sessions on; defaults to claude.
   */
  harness: string;
  /**
   * Every live session holding an In Progress task, oldest first; `url` is empty for one the loop did not start.
   */
  inFlight?: SchedulerSession[];
  /**
   * The `kind-decide` tasks in the eligible lane, which the scheduler never starts: the operator decides.
   */
  needsOperator?: SchedulerOperatorTask[];
  /**
   * Null when no task in the eligible lane is workable.
   */
  next?: SchedulerNext | null;
  /**
   * Harnesses whose admission is paused until `until`. Absent when none are paused.
   */
  pauses?: SchedulerPause[];
  /**
   * Null when no window holds admission back.
   */
  quietHours?: QuietHours | null;
  sampledAt: number | null;
  /**
   * Each harness's in-flight count against its session cap; the Sessions meter follows `harness`.
   */
  sessionsByHarness?: {
    [k: string]: SchedulerHarnessSessions;
  };
}
/**
 * One capacity dimension's use against its limit: percent for `cpu` and `memory`, a count for `sessions`, points for `review`.
 */
export interface SchedulerDimension {
  limit: number;
  name: "cpu" | "memory" | "sessions" | "review";
  use: number;
}
/**
 * A session the scheduler started whose task is still running: the strip's Sessions menu draws one row of it.
 */
export interface SchedulerSession {
  /**
   * The task's agent profile, empty when it has none.
   */
  model: string;
  /**
   * When the loop started the session, in epoch seconds.
   */
  started: number;
  task: string;
  title: string;
  /**
   * The session's address, as `start` answered it.
   */
  url: string;
}
/**
 * A task in the eligible lane that waits on the operator's decision rather than on capacity.
 */
export interface SchedulerOperatorTask {
  task: string;
  title: string;
}
/**
 * The task the loop would admit next, or, when none fits, the top-ranked one and what it waits on.
 */
export interface SchedulerNext {
  /**
   * The Priority matrix cell the task ranked by, `<impact>/<urgency>`, or `default` when it has no Impact or Urgency.
   */
  priority: string;
  /**
   * `goes next`, `quiet hours` while the quiet hours hold admission, `<harness> usage limit` while that harness is paused, or the first dimension the task overfits, which the strip shows after `waits:`.
   */
  reason: string;
  task: string;
  title: string;
  verdict: "starting" | "waits";
}
/**
 * A harness whose admission is paused until `until` after a usage or credit limit.
 */
export interface SchedulerPause {
  harness: string;
  reason: string;
  /**
   * When admission for this harness may resume, in epoch seconds.
   */
  until: number;
}
/**
 * A daily window in which the scheduler admits nothing: `start` up to `end`, `HH:MM` in `timezone`; an `end` before
 * `start` runs past midnight.
 */
export interface QuietHours {
  end: string;
  start: string;
  /**
   * The IANA zone the window's times are read in, such as America/Phoenix.
   */
  timezone: string;
}
/**
 * One harness's scheduler sessions in flight against its own session cap.
 */
export interface SchedulerHarnessSessions {
  limit: number;
  use: number;
}
/**
 * `GET /api/analytics/graph`: the branching directly-follows graph of each transition, Codex left out.
 */
export interface FlowGraph {
  graph: FlowEdge[];
  now: number;
  window_s: number;
}
/**
 * One directly-follows edge of a transition's graph.
 */
export interface FlowEdge {
  /**
   * Occurrences of the edge.
   */
  count: number;
  /**
   * `source` is a judgement cut: the agent chose there.
   */
  cut: boolean;
  kind: string;
  /**
   * Runs (tasks) the edge occurred in.
   */
  runs: number;
  /**
   * Of the occurrences that leave `source`.
   */
  share: number;
  size: number;
  /**
   * The skill in force: the transition.
   */
  skill: string;
  /**
   * An activity, or `[start]`.
   */
  source: string;
  /**
   * The activity that directly follows it, or `[end]`.
   */
  target: string;
}
/**
 * `GET /api/harnesses`: the tiers in order and each harness with its models and efforts.
 */
export interface Harnesses {
  harnesses: HarnessBody[];
  tiers: string[];
}
export interface HarnessBody {
  label: string;
  name: string;
  reason: string | null;
  sessions: boolean;
  tiers: {
    [k: string]: HarnessTier;
  };
}
export interface HarnessTier {
  efforts: string[];
  model: string;
  models?: {
    [k: string]: string;
  } | null;
  run_efforts?: {
    [k: string]: string;
  } | null;
}
/**
 * `GET /api/analytics/health`: the Board's flow health over a window.
 */
export interface Health {
  now: number;
  states: HealthState[];
  stuck: HealthStuck[];
  stuck_after_s: number;
  throughput: HealthThroughput;
  warnings: (GapWarning | UnknownLaneWarning)[];
  window_s: number;
}
export interface HealthState {
  final: boolean;
  id: string;
  max_s?: number | null;
  mean_s?: number | null;
  name: string;
  open?: number | null;
  visits?: number | null;
  wip: number;
}
export interface HealthStuck {
  counted_to_now: boolean;
  dwell_s: number;
  since: number;
  state: string;
  task: string;
}
export interface HealthThroughput {
  count: number;
  per_day: number;
}
/**
 * The history lost entries between two ids, so any number here may miss some.
 */
export interface GapWarning {
  after_id: string;
  before_id: string;
  kind: "gap";
  lost: number;
  message: string;
  stream: string;
}
/**
 * A lane that is no Board state.
 */
export interface UnknownLaneWarning {
  kind: "unknown_lane";
  lane: string;
  message: string;
}
/**
 * `GET /api/history?task=`: a task's lane changes, oldest first.
 */
export interface LaneHistory {
  path: LaneStep[];
  task: string;
}
export interface LaneStep {
  at: number;
  by?: string | null;
  from: string | null;
  to: string;
}
/**
 * `GET /api/ledger/<event>`, and the first event of `GET /api/ledger/<event>/events`: a Ledger's rows, newest first,
 * and whether older ones remain.
 */
export interface LedgerPage {
  more: boolean;
  rows: LedgerRow[];
}
/**
 * A later event of `GET /api/ledger/<event>/events`: the rows that are new or differ; every other row stands.
 */
export interface LedgerChange {
  rows: LedgerRow[];
}
/**
 * `GET /api/history?task=&machine=`: a task's path on one machine, and how many steps it has taken.
 */
export interface MachineHistory {
  machine: string;
  path: MachineStep[];
  steps: number;
  task: string;
}
export interface MachineStep {
  at: number;
  event: string;
  state: string;
}
/**
 * `GET /api/machines`: the next page of machines entered from `open`.
 */
export interface Machines {
  machines: MachineRow[];
  more: boolean;
  open: string | null;
}
/**
 * A machine of `GET /api/machines`: whole, with its derivation.
 */
export interface MachineRow {
  agents: RawTask[];
  chain: string[];
  depth: number;
  last: number | null;
  machine: Machine;
  name: string;
  nested: string[];
  parent: string | null;
  stuck: Stuck | null;
  ties: Tie[];
}
export interface Machine {
  /**
   * Only the board machine: the writers that are runs workflows.
   */
  dagActors?: string[] | null;
  /**
   * Only the board machine: the skill machine each launching DAG starts.
   */
  launches?: {
    [k: string]: Launch;
  } | null;
  /**
   * Only the board machine: the state ids along its axis, in order (New to Done).
   */
  mainLine?: string[] | null;
  /**
   * The edge a finished skill hands to; null when the machine declares none.
   */
  next?: HeldNext | null;
  /**
   * The third party whose events move this machine ("GitHub"); absent for a machine StarPulse's own actors move.
   */
  source?: string | null;
  states: MachineState[];
  /**
   * The machines that open under this machine's states; the board's first is its In Progress delivery machine.
   */
  submachines?: Submachine[] | null;
  /**
   * Only the board machine: the state ids the Star Map draws at each stage, left to right, a tier's states stacked in its cell; a state no tier names is drawn with the tier at the mean of the tiers its transitions join it to, stacked in it or in a tier of its own after it, else in a tier of its own after the last, and with none the Board draws its own columns.
   */
  tiers?: string[][] | null;
  transitions: Transition[];
  /**
   * Its YAML-declared writers per event.
   */
  writers?: {
    [k: string]: Writer[];
  } | null;
}
/**
 * A runs workflow's launch: the skill it starts and the machine that skill draws, null when it has none.
 */
export interface Launch {
  machine: string | null;
  skill: string;
}
export interface MachineState {
  final: boolean;
  id: string;
  initial: boolean;
  name: string;
  /**
   * The type the machine declares the state: `initial`, `final`, `resting`, `waiting_on_fact` or `waiting_on_person`; null when it declares none.
   */
  role?: string | null;
}
/**
 * Where a Board state opens into another machine, and which Board event each inner final state fires.
 */
export interface Submachine {
  exits: {
    [k: string]: string;
  };
  machine: string;
  /**
   * The machine the link opens under: `board`, or the machine whose `state` it hangs off.
   */
  parent: string;
  state: string;
  /**
   * What has to hold for the inner machine to run under `state`; empty when always.
   */
  when: string;
}
export interface Transition {
  /**
   * The skill sentence that authorizes the transition; absent when its YAML cites none.
   */
  cite?: Cite | null;
  event: string;
  source: string;
  target: string;
}
/**
 * The sentence of a skill that sends a session down a transition.
 */
export interface Cite {
  quote: string;
  skill: string;
}
/**
 * Who fires a Board event: a runs workflow (by `<instance>/<workflow>` name), `operator` or `agent`.
 */
export interface Writer {
  actor: string;
  trigger: string;
}
/**
 * The longest-stuck task of a machine and every machine nested below it: idle over two hours outside a final state.
 */
export interface Stuck {
  machine: string;
  /**
   * When the task last moved, epoch seconds.
   */
  since: number;
  state: string;
}
/**
 * Where a lifecycle machine is entered from.
 *
 * `declared` is a Submachine on `machine`'s `state`; `observed` is the state the task held on `machine` when its session
 * entered this one; `dag` is a launch by `dag`, which names no machine or state. `count` is the sessions entered
 * through it, null for a launch.
 */
export interface Tie {
  count: number | null;
  dag: string | null;
  kind: "declared" | "observed" | "dag";
  machine: string | null;
  state: string | null;
  /**
   * What has to hold for a declared tie to run; empty otherwise.
   */
  when: string;
}
/**
 * `GET /api/milestones/<id>`: one open milestone.
 */
export interface MilestoneShown {
  milestone: MilestoneRecord;
}
/**
 * A milestone as the board's reader gives it: its sections as text and bullet lists, and its whole description.
 */
export interface MilestoneRecord {
  adrs: string[];
  description: string;
  id: string;
  outcome: string;
  retro: string;
  specs: string[];
  title: string;
}
/**
 * `GET /api/milestones`: every open milestone, by ascending number.
 */
export interface Milestones {
  milestones: MilestoneRecord[];
}
/**
 * `GET /api/analytics/missed-loads`: per declared skill, the cases that ran its trigger without loading it.
 */
export interface MissedLoads {
  now: number;
  skills: MissedSkill[];
  window_s: number;
}
/**
 * A declared skill: the cases that performed what should load it, and those that did not load it.
 */
export interface MissedSkill {
  /**
   * The `list` most recent missed cases, newest first.
   */
  listed: CaseRef[];
  missed: number;
  performed: number;
  skill: string;
}
/**
 * One session's work on one task (`task` None: a branch that names none).
 */
export interface CaseRef {
  harness: string;
  last_at: number;
  session: string;
  task: string | null;
}
/**
 * `GET /api/pulls`: the stored pull requests matching every filter given, by repository then number.
 */
export interface Pulls {
  pulls: PullRecord[];
}
/**
 * One pull request the PR store read from GitHub, as of `fetchedAt` (epoch seconds).
 *
 * `headRefName` and `unresolvedThreads` (the first 100 threads) are null for a record saved before they were kept.
 */
export interface PullRecord {
  baseRefName: string;
  body: string;
  checks: "pass" | "failing" | "pending" | "none";
  fetchedAt: number;
  headRefName: string | null;
  headRefOid: string;
  isDraft: boolean;
  mergeSha: string | null;
  mergeable: string;
  mergedAt: string | null;
  number: number;
  repo: string;
  requiredChecks: RequiredCheck[];
  state: "OPEN" | "MERGED" | "CLOSED";
  threads: number;
  unresolvedThreads: PullThread[] | null;
  updatedAt: string;
}
export interface RequiredCheck {
  name: string;
  result: "pass" | "failing" | "pending";
}
/**
 * An unresolved review thread: its id and the login of its first comment's author, null for a deleted account.
 */
export interface PullThread {
  author: string | null;
  id: string;
}
/**
 * `POST /api/move`: move `task`, or each of `tasks` in one call, to the column `to`.
 */
export interface MoveRequest {
  actor?: string | null;
  harness?: string | null;
  session?: string | null;
  task?: string | null;
  tasks?: [string, ...string[]] | null;
  to: string;
}
/**
 * `POST /api/start`: start a session for `task` on `profile`; `harness` defaults to `claude`.
 *
 * `assignee` is the legacy name of `profile` and is read when `profile` is absent.
 */
export interface StartRequest {
  actor?: string | null;
  assignee?: string | null;
  harness?: string | null;
  mode?: string | null;
  profile?: string | null;
  session?: string | null;
  task: string;
}
/**
 * `POST /api/edit`: change fields of `task`; `base` holds the value each changed field had when the page read it.
 */
export interface EditRequest {
  actor?: string | null;
  base: {
    [k: string]: unknown;
  };
  breakGlass?: boolean;
  changes: {
    [k: string]: unknown;
  };
  comment?: string | null;
  harness?: string | null;
  session?: string | null;
  task: string;
}
/**
 * `POST /api/archive`: archive `task`, or each of `tasks` in one call, recording `reason` when it is not blank.
 */
export interface ArchiveRequest {
  actor?: string | null;
  harness?: string | null;
  reason?: string | null;
  session?: string | null;
  task?: string | null;
  tasks?: [string, ...string[]] | null;
}
/**
 * `POST /api/verdict`: record `verdict` (`pass` or `miss`) for `check` of `task`'s `## Post-merge Checks`.
 *
 * A `miss` names the task `fix` that repairs it; `evidence` is kept in the verdict's comment.
 */
export interface VerdictRequest {
  actor?: string | null;
  check: string;
  evidence?: string | null;
  fix?: string | null;
  harness?: string | null;
  session?: string | null;
  task: string;
  verdict: string;
}
/**
 * `POST /api/rating`: record one change of `task`'s pass/fail rating: `pass`, `fail` with an optional `reason`, or
 * `cleared`. Every change is kept; the latest one is the task's rating.
 */
export interface RatingRequest {
  actor?: string | null;
  harness?: string | null;
  reason?: string | null;
  session?: string | null;
  task: string;
  verdict: "pass" | "fail" | "cleared";
}
/**
 * `POST /api/miss`: file the task `fix` and record `check` of `task` as missed, naming it, in one write.
 */
export interface MissRequest {
  actor?: string | null;
  check: string;
  evidence?: string | null;
  fix: CreateSpec;
  harness?: string | null;
  reason?: string | null;
  session?: string | null;
  task: string;
}
/**
 * One task a create files: its `title` and details, and an optional `ref` that a sibling in the same batch names
 * as `ref:<label>` in its `dependencies`.
 *
 * Text is trimmed; list items are trimmed and blank ones dropped, or refused where the list must hold only text.
 * `task`, `size` and `skill` are read and left unused by a create.
 */
export interface CreateSpec {
  acceptanceCriteria?: string[] | null;
  assignee?: string | null;
  definitionOfDone?: string[] | null;
  dependencies?: string[] | null;
  description?: string | null;
  documentation?: string[] | null;
  impact?: string | null;
  labels?: string[] | null;
  milestone?: string | null;
  priority?: string | null;
  profile?: string | null;
  ref?: string | null;
  references?: string[] | null;
  size?: string | null;
  skill?: string | null;
  source?: string | null;
  status?: string | null;
  task?: string | null;
  title: string;
  type?: string | null;
  urgency?: string | null;
}
/**
 * `POST /api/restore`: return the archived task `task` to the board's tasks, unchanged; the writer names who did.
 */
export interface RestoreRequest {
  actor?: string | null;
  harness?: string | null;
  session?: string | null;
  task: string;
}
/**
 * `POST /api/retire`: take the finished task `task` off the board into the history store's retired tasks.
 */
export interface RetireRequest {
  task: string;
}
/**
 * `POST /api/take-over`: flip the unattended task `task` to interactive; its workflow types nothing more.
 */
export interface TakeOverRequest {
  task: string;
}
/**
 * `POST /api/retired/import`: keep the retired task file `name`, holding `text`, in the history store.
 */
export interface RetiredImportRequest {
  name: string;
  text: string;
}
/**
 * `POST /api/complete`: move the Done task `task` into the board's completed tasks.
 */
export interface CompleteRequest {
  task: string;
}
/**
 * `POST /api/claim`: move `task` to In Progress and record `session` as its assignee, an opaque string; the same
 * assignee claiming again changes nothing, and an assignee already on another open claim is refused.
 */
export interface ClaimRequest {
  actor?: string | null;
  harness?: string | null;
  session?: string | null;
  task: string;
}
/**
 * `POST /api/park`: pause `task` on exactly one reason, which picks the lane: `untilTask` (tasks that must reach
 * Done) and `until` (criteria a check can observe) wait; `operator` (what only the operator can do) needs attention.
 */
export interface ParkRequest {
  actor?: string | null;
  comment?: string | null;
  harness?: string | null;
  operator?: string | null;
  session?: string | null;
  task: string;
  until?:
    | {
        [k: string]: unknown;
      }[]
    | null;
  untilTask?: string[] | null;
}
/**
 * `POST /api/review`: move `task` to Review, adding `references` and `summary` first so the configured rules judge
 * the record the move would leave.
 */
export interface ReviewRequest {
  actor?: string | null;
  comment?: string | null;
  harness?: string | null;
  references?: string[] | null;
  session?: string | null;
  summary?: string | null;
  task: string;
}
/**
 * `POST /api/tasks`: create a task in the lane `status` names or else the board's starting lane, stamped
 * `created_by: <harness>:<session>`, or each of `tasks` in one call, each with its own title and details.
 */
export interface CreateRequest {
  acceptanceCriteria?: string[] | null;
  actor?: string | null;
  assignee?: string | null;
  definitionOfDone?: string[] | null;
  dependencies?: string[] | null;
  description?: string | null;
  documentation?: string[] | null;
  harness?: string | null;
  impact?: string | null;
  labels?: string[] | null;
  milestone?: string | null;
  priority?: string | null;
  profile?: string | null;
  ref?: string | null;
  references?: string[] | null;
  session?: string | null;
  size?: string | null;
  skill?: string | null;
  source?: string | null;
  status?: string | null;
  task?: string | null;
  tasks?: [CreateSpec, ...CreateSpec[]] | null;
  title?: string | null;
  type?: string | null;
  urgency?: string | null;
}
/**
 * `POST /api/milestones`: open a milestone; only the title is required.
 */
export interface MilestoneCreateRequest {
  adrs?: string[] | null;
  outcome?: string | null;
  retro?: string | null;
  specs?: string[] | null;
  title: string;
}
/**
 * `POST /api/milestones/edit`: replace the `title`, `outcome`, `specs`, `adrs` or `retro` `changes` names.
 */
export interface MilestoneEditRequest {
  changes: {
    [k: string]: unknown;
  };
  milestone: string;
}
/**
 * `POST /api/milestones/archive`: archive `milestone`.
 */
export interface MilestoneArchiveRequest {
  milestone: string;
}
/**
 * `POST /api/docs`: file a doc; only the title is required. `type` is `specification`, `guide`, `readme` or `other`.
 */
export interface DocCreateRequest {
  body?: string | null;
  folder?: string | null;
  title: string;
  type?: string | null;
}
/**
 * `POST /api/docs/edit`: replace the `title`, `type` or `body` `changes` names.
 */
export interface DocEditRequest {
  changes: {
    [k: string]: unknown;
  };
  doc: string;
}
/**
 * `POST /api/docs/archive`: archive `doc`.
 */
export interface DocArchiveRequest {
  doc: string;
}
/**
 * `POST /api/docs/restore`: return the archived doc `doc` to `folder` under the board's docs (the docs folder
 * itself when absent), unchanged.
 */
export interface DocRestoreRequest {
  doc: string;
  folder?: string | null;
}
/**
 * `PUT /api/history-window`: set the shared history window.
 */
export interface WindowRequest {
  hours: number;
}
/**
 * `PUT /api/scheduler`: whether the scheduler admits tasks, which harness it starts on, and/or its quiet hours.
 */
export interface SchedulerRequest {
  enabled?: boolean | null;
  harness?: string | null;
  quietHours?: QuietHours | null;
}
/**
 * The server was told to stop and will not answer after this: sent to every open stream before it exits.
 */
export interface RestartingEvent {
  at: number;
}
/**
 * `GET /api/retired[?task=<id>]`: every retired task, or the one `task` names, by id.
 */
export interface RetiredTasks {
  tasks: RetiredTask[];
}
/**
 * A retired task as the board's history store keeps it: its id, its file name and the file's text, byte-for-byte.
 */
export interface RetiredTask {
  name: string;
  task: string;
  text: string;
}
/**
 * `GET /api/search?q=&limit=&label=&finished_within_days=`: the tasks holding every word of `q`, best match first,
 * each carrying every `label` and, with `finished_within_days`, open or finished within that many days.
 */
export interface SearchResults {
  hits: SearchHit[];
  query: string;
}
/**
 * One task a search found: where it is now, and the text around the match.
 */
export interface SearchHit {
  lane: string;
  score: number;
  snippet: string;
  task: string;
  title: string;
}
/**
 * `GET /api/analytics/steps`: every model request of a window, oldest first.
 */
export interface SessionSteps {
  now: number;
  steps: SessionStep[];
  window_s: number;
}
/**
 * One model request of a harness session, with the skill in force when it ran and the calls it made.
 */
export interface SessionStep {
  /**
   * What each call it made performed, in order, with no arguments.
   */
  activities: string[];
  /**
   * When the request was logged, in epoch seconds.
   */
  at: number;
  /**
   * False for a harness the steps-per-completion ledger does not cover (Codex).
   */
  captured: boolean;
  /**
   * The purpose an eval run stamped with the configured `eval_attribute`; empty for any other request.
   */
  eval: string;
  harness: string;
  /**
   * One per call: the shell command the instance's redactor left, else the tool's name.
   */
  keys: string[];
  model: string;
  origin: "main" | "side" | "auxiliary";
  session: string;
  /**
   * The skill most recently loaded in the session, counting this step's own; `none` before any.
   */
  skill: string;
  task: string | null;
  tokens: TokenCounts;
}
export interface TokenCounts {
  cache_read: number;
  cache_write: number;
  input: number;
  output: number;
  reasoning: number;
}
/**
 * `GET /api/analytics/sessions`: session and slice health over a window.
 */
export interface Sessions {
  now: number;
  sessions: SessionHealth[];
  slices: SliceHealth[];
  window_s: number;
}
/**
 * One harness session's work on one task (`task` None: a branch that names none), from its OTLP signals.
 */
export interface SessionHealth {
  agent_s: number;
  compactions: {
    [k: string]: number;
  };
  complete: boolean;
  cost_usd: number | null;
  effort_changes: number;
  efforts: string[];
  eval: string;
  first_at: number;
  gates: {
    [k: string]: number;
  };
  harness: string;
  idle_s: number;
  interrupts: number;
  kind: "headless" | "interactive" | "unknown";
  last_at: number;
  lowers: number;
  main_effort: string | null;
  main_model: string | null;
  model_changes: number;
  models: string[];
  operator_prompts: number;
  operator_wait_s: number;
  prompt_labels: {
    [k: string]: number;
  };
  prompts: number;
  raises: number;
  rejections: {
    [k: string]: number;
  };
  requests: number;
  session: string;
  side_requests: number;
  skills: {
    [k: string]: number;
  };
  steps_before_edit: number | null;
  task: string | null;
  tokens: TokenCounts;
  tool_calls: number;
  tool_failures: number;
  tools: {
    [k: string]: number;
  };
  user_rejects: number;
}
/**
 * What the sessions that worked one task did together.
 */
export interface SliceHealth {
  active_s: number;
  clean: boolean;
  compactions: number;
  complete: boolean;
  cost_usd: number | null;
  efforts: string[];
  escalated: boolean;
  first_at: number;
  harnesses: string[];
  idle_s: number;
  interrupts: number;
  interventions: number;
  last_at: number;
  lowers: number;
  models: string[];
  operator_prompts: number;
  operator_wait_s: number;
  prompt_labels: {
    [k: string]: number;
  };
  raises: number;
  rejections: number;
  sessions: number;
  side_steps: number;
  skills: {
    [k: string]: number;
  };
  steps: number;
  steps_before_edit: number | null;
  task: string;
  tokens: TokenCounts;
  tool_calls: number;
  user_rejects: number;
}
export interface Snapshot {
  /**
   * The Backlog board a task links into.
   */
  boardUrl?: string | null;
  /**
   * What the board writes: the task modal draws Edit and Archive only when its board does.
   */
  capabilities?: Capabilities | null;
  /**
   * Each task's latest In Progress claim the board writer refused an agent, and when (epoch seconds).
   */
  claims?: {
    [k: string]: Claim;
  } | null;
  /**
   * The ids of the done tasks from before local midnight that the board feed holds as a stub, left out of `flows`: the full view (`?view=full`) only, the page reads them from `/api/done` and `/api/task/<id>`.
   */
  cold_done?: string[] | null;
  /**
   * The CPU share of each runs instance's scheduler and workers, by instance name.
   */
  cpu?: {
    [k: string]: Cpu;
  } | null;
  /**
   * The DAGs cued by a Board event.
   */
  cues?: Cue[] | null;
  dags: DagBody[];
  /**
   * The DAG domains.
   */
  domains?: Domain[] | null;
  error: string | null;
  flows: FlowSnapshot[];
  /**
   * Every lifecycle machine the server draws, and `runs`.
   */
  graphs: string[];
  /**
   * A Backlog.md project found beside the config while the default board is shown, and how to switch to it.
   */
  hint?: string | null;
  /**
   * Each task an accepted take-over made interactive, by task id; a task never taken over is absent.
   */
  interactive?: {
    [k: string]: boolean;
  } | null;
  machinePage?: MachinePage | null;
  machineStrip?: MachineStrip | null;
  /**
   * The pinned merge rows of the last day that the newest page leaves out.
   */
  mergePins?: LedgerRow[] | null;
  mergeStrip?: MergeStrip | null;
  /**
   * How many tasks each milestone has completed, counted over every settled task though `settled` holds only the recent ones.
   */
  milestone_done?: {
    [k: string]: number;
  } | null;
  /**
   * Each distinct set of Board-column verdicts a task's `move_set` names, by key.
   */
  move_sets?: {
    [k: string]: {
      [k: string]: Move;
    };
  } | null;
  now: number;
  /**
   * The concurrency pools the DAGs run on.
   */
  pools?: Pool[] | null;
  /**
   * Each open task's pull requests, by task id.
   */
  pulls?: {
    [k: string]: Pull[];
  } | null;
  /**
   * Each rated task's latest pass/fail rating, by task id; a task never rated is absent.
   */
  ratings?: {
    [k: string]: Rating;
  } | null;
  /**
   * True while a just-started server is still reading its board: its Board is partial until a snapshot without it follows.
   */
  reading?: boolean | null;
  /**
   * Which State plays which part on the board.
   */
  roles?: Roles | null;
  settled: {
    [k: string]: Settled;
  };
}
/**
 * What the board writes beyond moves: the page draws Edit, Archive… and New task only for what its board does.
 */
export interface Capabilities {
  archive: boolean;
  create?: boolean | null;
  edit: boolean;
}
export interface Claim {
  at: number;
  reason: string;
}
/**
 * A DAG that runs on the same trigger as a Board event's writer but writes no lane itself.
 */
export interface Cue {
  dag: string;
  event: string;
  /**
   * Seconds after the event a run of the DAG may take to start before the Ledger draws the merge overdue.
   */
  grace?: number;
  on: string;
  /**
   * How a failed run of the DAG clears: `forced` only on a green forced rerun, `next` on the DAG's next green run.
   */
  resolves?: ("forced" | "next") | null;
  state: string;
}
/**
 * A domain's DAGs, and whether each is declared safe to run from the page; `processes` package them when configured.
 */
export interface Domain {
  dags: DomainDag[];
  name: string;
  processes?: DomainProcess[];
}
export interface DomainDag {
  name: string;
  runSafe: boolean;
}
/**
 * A named package of a domain's DAGs.
 */
export interface DomainProcess {
  dags: DomainDag[];
  name: string;
}
export interface FlowSnapshot {
  agents: RawTask[];
  chain?: string[] | null;
  depth?: number | null;
  last?: number | null;
  machine: Machine;
  name: string;
  nested?: string[] | null;
  parent?: string | null;
  stuck?: Stuck | null;
  ties?: Tie[] | null;
}
/**
 * The first page of machines entered from `open`, by name; their bodies are in the snapshot's `flows`.
 */
export interface MachinePage {
  machines: string[];
  more: boolean;
  open: string | null;
}
/**
 * The last 24 hours of machine entries, counted over every machine.
 */
export interface MachineStrip {
  entries: MachineEntry[];
}
export interface MachineEntry {
  at: number;
  dag: string | null;
  from: MachineEntryFrom | null;
  machine: string;
  row: string;
}
export interface MachineEntryFrom {
  machine: string;
  state: string;
}
/**
 * A task's latest pass/fail rating: its verdict, the reason it names (empty when none), when it was set (epoch
 * seconds), who set it (`actor`, empty when the write named none) and how many changes the task's rating has had.
 */
export interface Rating {
  actor: string;
  at: number;
  changes: number;
  reason: string;
  verdict: string;
}
/**
 * Which of the board's States play which part, as its machine declares them: a client reads these and never a
 * State's name.
 */
export interface Roles {
  /**
   * Where a task waits on a person.
   */
  attention?: string | null;
  /**
   * Where the work is done: a resting State, else the final one.
   */
  done?: string | null;
  /**
   * Where a task is settled for good.
   */
  final?: string | null;
  /**
   * Where a task starts.
   */
  initial?: string | null;
  /**
   * Where a task waits to be picked up.
   */
  ready?: string | null;
  /**
   * Where a task waits on its pull request.
   */
  review?: string | null;
  /**
   * The States a session starts a task from.
   */
  startable?: string[];
  /**
   * Where a task waits on its Start Criteria or dependencies.
   */
  waiting?: string | null;
  /**
   * Where a session works a task.
   */
  working?: string | null;
}
/**
 * `GET /api/analytics/stages`: sub-stages and their stability from one window to the one before.
 */
export interface SubStages {
  now: number;
  stages: SubStage[];
  window_s: number;
}
/**
 * One stage mined at the judgement cuts of the stretches no skill governs, this week and the week before.
 */
export interface SubStage {
  kind: string;
  median_activities: number | null;
  previous_median_activities: number | null;
  /**
   * Runs it occurred in over the window before.
   */
  previous_runs: number;
  /**
   * Runs the stage occurred in over the window; 0 when it did not occur.
   */
  runs: number;
  size: number;
  /**
   * Of the cell: stages in both windows over stages in either; None when a window mined none.
   */
  stability: number | null;
  /**
   * The cut that opens the stage, `[start]` for the first.
   */
  stage: string;
}
/**
 * `GET /api/history?task=&hours=`: every machine event of a task in the window, oldest first.
 */
export interface TaskEventHistory {
  events: MachineEvent[];
  hours: number;
  task: string;
}
export interface MachineEvent {
  at: number;
  event: string;
  from: string;
  machine: string;
  to: string;
}
/**
 * `GET /api/task/<id>`: the full record of a task from the board's reader, keyed by its editable fields.
 */
export interface TaskRecord {
  record: {
    [k: string]: unknown;
  };
  task: string;
}
/**
 * `GET /api/analytics/trace-clusters`: recurring work, ranked by distinct sessions.
 */
export interface TraceClusters {
  /**
   * Cases with a trace in the window.
   */
  cases: number;
  /**
   * Cases that joined a cluster, whatever its size.
   */
  clustered: number;
  clusters: TraceCluster[];
  min_sessions: number;
  now: number;
  threshold: number;
  window_s: number;
}
/**
 * Cases that did the same distinctive work, and the skills that covered it.
 */
export interface TraceCluster {
  cases: number;
  /**
   * The features with the most weight across the cases: `a:` activity, `r:` area read, `w:` area written.
   */
  descriptors: string[];
  first_at: number;
  /**
   * A stable id: the digest of the sorted descriptors.
   */
  key: string;
  kinds: {
    [k: string]: number;
  };
  last_at: number;
  /**
   * Null unless `outliers` was asked for.
   */
  medoid: ClusterMedoid | null;
  missed_loads: ClusterMissed[];
  outliers: ClusterOutlier[];
  sample_sessions: string[];
  sample_tasks: string[];
  sessions: number;
  /**
   * The three most loaded skills, less the lifecycle skills.
   */
  skills: ClusterSkill[];
  tasks: string[];
  titles: string[];
  /**
   * Cases that loaded no skill beyond the lifecycle skills.
   */
  uncovered: number;
}
/**
 * The case nearest every other by normalized LCS distance between traces, and the cluster's usual spread.
 */
export interface ClusterMedoid {
  case: CaseRef;
  median_distance: number;
  trace: string[];
}
export interface ClusterMissed {
  missed: number;
  performed: number;
  skill: string;
}
/**
 * A case far from the medoid: `deletions` are the medoid's activities it lacks, `insertions` its own extra.
 */
export interface ClusterOutlier {
  case: CaseRef;
  deletions: string[];
  distance: number;
  insertions: string[];
}
export interface ClusterSkill {
  cases: number;
  skill: string;
}
/**
 * The trajectory analytics: the paths of the runs that ended in a terminal over a window.
 */
export interface Trajectories {
  betweenness: {
    [k: string]: number;
  };
  bottleneck: Bottleneck | null;
  calibration: Calibration;
  chain: {
    [k: string]: ChainState;
  };
  ended: number;
  forecast: Forecast[];
  gates: GateSummary[];
  goal: string;
  history_s: number;
  loops: LevelLoop[];
  machine: string;
  norm: Norm | null;
  now: number;
  outliers: Outlier[];
  runs: TrajectoryRun[];
  variants: Variant[];
  window_s: number;
}
export interface Bottleneck {
  path_days: number;
  state: string;
}
/**
 * The forecast scored on the latest fifth of the ended runs against a chain fitted on the others.
 */
export interface Calibration {
  calibrated: boolean | null;
  deciles: Decile[];
  fit: number;
  held_out: number;
  predictions: number;
  unscored: number;
}
/**
 * One decile of forecast chance of the goal on the held-out runs: its forecasts' mean against the share of
 * their runs that reached the goal, null when it holds none.
 */
export interface Decile {
  high: number;
  low: number;
  n: number;
  observed: number | null;
  predicted: number | null;
  runs: number;
}
export interface ChainState {
  expected_days: number;
  p_goal: number;
}
/**
 * One run still going: where it is, its loops so far, and from its state's row the chance of each terminal and
 * of the goal and its expected days to finish, with `n`, the times that row was seen leave. Null with no row.
 */
export interface Forecast {
  expected_days: number | null;
  loops: number;
  n: number;
  p: {
    [k: string]: number;
  } | null;
  p_goal: number | null;
  pooled: boolean;
  since: number;
  source: string;
  state: string;
  task: string;
}
export interface GateSummary {
  bypassable: boolean;
  bypassed: number;
  crossed: number;
  gate: string;
  mandatory: number;
  runs: number;
  witness: GateWitness | null;
}
export interface GateWitness {
  path: string[];
  task: string;
}
/**
 * One back-edge across the runs that took it, summed from the runs' own figures.
 */
export interface LevelLoop {
  days: number;
  from: string;
  runs: number;
  to: string;
  trips: number;
}
export interface Norm {
  count: number;
  path: string[];
}
export interface Outlier {
  distance: number;
  path: string[];
  source: string;
  task: string;
}
export interface TrajectoryRun {
  back_edges: number;
  gates: RunGate[];
  loops: RunLoop[];
  path: string[];
  reached_goal: boolean;
  sccs: number;
  source: string;
  task: string;
}
export interface RunGate {
  crossed: boolean;
  dominators: string[];
  gate: string;
  mandatory: boolean;
  post_dominators: string[];
  witness: string[] | null;
}
/**
 * One back-edge a run took: its trips and the days they took, from the target's previous visit to each return.
 */
export interface RunLoop {
  days: number;
  from: string;
  to: string;
  trips: number;
}
export interface Variant {
  count: number;
  path: string[];
  share: number;
}
/**
 * `GET /api/analytics/transitions`: what each skill cost within each kind and size, Codex left out.
 */
export interface Transitions {
  now: number;
  transitions: TransitionCost[];
  window_s: number;
}
/**
 * The cost of one skill in force, within one kind and size of task.
 */
export interface TransitionCost {
  /**
   * The seconds of the steps' requests and tool calls.
   */
  agent_s: number;
  /**
   * The `kind-*` label of the tasks, without the prefix.
   */
  kind: string;
  /**
   * The most input, cache-read and cache-write tokens one request held.
   */
  peak_context: number;
  /**
   * The subagents' share of `steps`.
   */
  side_steps: number;
  /**
   * The `size-*` label of the tasks.
   */
  size: number;
  /**
   * The skill in force on the steps; `none` before any load.
   */
  skill: string;
  /**
   * Model requests, a subagent's included.
   */
  steps: number;
  tasks: number;
  wasted_rate: number;
  /**
   * Steps with a call that failed, was refused by a guard or hook, or repeats the command before it.
   */
  wasted_steps: number;
}
/**
 * `/api/history-window`: the effective window, the declared default, and whether Admin's override is in effect.
 */
export interface WindowState {
  default: number;
  hours: number;
  overridden: boolean;
}
