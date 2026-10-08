/* Generated from starpulse/api.schema.json by pnpm run gen:types; edit starpulse/contracts/api.py, not this file. */

/**
 * The root of `api.schema.json`: every body as a property, so the generated types name each one.
 */
export interface ApiContract {
  answers: (
    | Moved
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
  )[];
  contractReport: ContractReport;
  docShown: DocShown;
  docs: Docs;
  events: (TaskDelta | MoveDelta | DagsDelta | PullsDelta | ClaimDelta | LedgersDelta | InsightDelta)[];
  forwardingStatus: ForwardingStatus;
  forwardingUnconfigured: ForwardingUnconfigured;
  harnesses: Harnesses;
  health: Health;
  laneHistory: LaneHistory;
  level: Level;
  machineHistory: MachineHistory;
  machines: Machines;
  merges: Merges;
  milestoneShown: MilestoneShown;
  milestones: Milestones;
  pulls: Pulls;
  requests: (
    | MoveRequest
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
  )[];
  snapshot: Snapshot;
  taskRecord: TaskRecord;
  trajectories: Trajectories;
  whatIf: WhatIf;
  windowState: WindowState;
}
export interface Moved {
  advice?: string | null;
  task: string;
  to: string;
}
export interface Edited {
  changed: string[];
  task: string;
}
export interface Archived {
  task: string;
}
export interface Created {
  task: string;
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
}
export interface ForwardAccepted {
  accepted: number;
  rejected: number;
}
export interface InsightPosted {
  id: string;
  replaced: boolean;
}
export interface InsightRetracted {
  id: string;
  retracted: boolean;
}
/**
 * Every refusal: what went wrong.
 */
export interface ApiError {
  error: string;
}
/**
 * A refusal a skill satisfies: the skill that produces what the guard needs.
 */
export interface SkillRefusal {
  error: string;
  skill: string;
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
 * A level window longer than the history, with the history's length.
 */
export interface WindowTooLong {
  error: string;
  history_s: number;
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
 * A Board task that moved (`agent` null once it left the lanes).
 */
export interface TaskDelta {
  agent: RawAgent | null;
  id: string;
  settled: Settled | null;
}
/**
 * A Backlog task. On the board its state is its lane; on every other machine, the state its latest machine event left it in.
 */
export interface RawAgent {
  active?: number | null;
  /**
   * When a Board task was created, in epoch seconds; null or absent when unknown.
   */
  created?: number | null;
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
  labels?: string[] | null;
  /**
   * A Board task's milestone; empty or absent when it has none.
   */
  milestone?: string | null;
  model: string;
  /**
   * The verdict on each Board column the task may move to, by state id.
   */
  moves?: {
    [k: string]: Move;
  } | null;
  /**
   * The Board lane the task left on its last move; absent before it has moved.
   */
  previous?: string | null;
  /**
   * A task's pull requests: the PR URLs among its references.
   */
  prs?: string[] | null;
  state: string;
  steps?: number | null;
  /**
   * A machine's task: the id of the Backlog task its events name.
   */
  task?: string | null;
  title: string;
  trail?: TrailStep[] | null;
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
 * The verdict on moving a task to one column: allowed, or guarded by a declared rule.
 */
export interface Move {
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
export interface TrailStep {
  at: number;
  event: string;
  state: string;
}
/**
 * A task that left the Board's lanes for good: where it settled, when, and the title, assignee and milestone it settled with.
 */
export interface Settled {
  at: number | null;
  created: number | null;
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
  agent: RawAgent;
  flow: string;
  id: string;
}
/**
 * A runs instance's workflows.
 */
export interface DagsDelta {
  dags: DagBody[];
  error: string | null;
  pools?: Pool[] | null;
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
  runId: string;
  startedAt: string;
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
   * The step's name, unique within its DAG.
   */
  name: string;
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
   * True when the last read failed and this is the read before it.
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
export interface LedgersDelta {
  ledgers: {
    [k: string]: LedgerRow[];
  };
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
 * A finding drawn, or retracted when `finding` is null.
 */
export interface InsightDelta {
  finding: Finding | null;
  id: string;
}
/**
 * One thing an external engine says about the flow, posted to `POST /api/insights`; a re-post of an `id` replaces it.
 */
export interface Finding {
  /**
   * When the engine wrote it, in epoch seconds.
   */
  created_at: number;
  engine: FindingEngine;
  /**
   * Where a reader can check it.
   */
  evidence?: Evidence[];
  /**
   * When the page should stop showing it, in epoch seconds, after `created_at`; None keeps it until it is retracted.
   */
  expires_at?: number | null;
  /**
   * The engine's stable key for the finding; posting it again replaces it.
   */
  id: string;
  scope?: FindingScope;
  /**
   * How much attention it asks for.
   */
  severity: "info" | "warn" | "act";
  /**
   * What the engine found, in plain text of at most 280 characters.
   */
  text: string;
}
/**
 * The engine that wrote it, by name and version.
 */
export interface FindingEngine {
  /**
   * The engine's name, stable across its releases.
   */
  name: string;
  /**
   * The engine release that wrote the finding.
   */
  version: string;
}
/**
 * One thing a reader can open to check a finding: a labelled link, or a labelled query over the history store.
 */
export interface Evidence {
  /**
   * What the link or query shows, in a few words.
   */
  label: string;
  /**
   * A read-only query over the history store's tables that returns the evidence; exactly one of `url` and `query` is set.
   */
  query?: string | null;
  /**
   * A link to the evidence; exactly one of `url` and `query` is set.
   */
  url?: string | null;
}
/**
 * What it is about: a team, machine, state or task, each optional.
 */
export interface FindingScope {
  /**
   * The machine the finding is about, as `<repo>/<machine>`.
   */
  machine?: string | null;
  /**
   * The state of that machine the finding is about.
   */
  state?: string | null;
  /**
   * The task key the finding is about.
   */
  task?: string | null;
  /**
   * The team key the finding is about, as a board task's `team`.
   */
  team?: string | null;
}
/**
 * What the forwarder would send next, and why.
 */
export interface ForwardingStatus {
  configured: true;
  contract: {
    [k: string]: ForwardedField[];
  };
  lastSent: number | null;
  more: boolean;
  names: boolean;
  next: ForwardedEntry[];
  optIn: boolean;
  problem: string | null;
  refused: boolean;
  url: string;
}
export interface ForwardedField {
  field: string;
  person: boolean;
}
export interface ForwardedEntry {
  fields: {
    [k: string]: unknown;
  };
  /**
   * The fields of an entry that stay on the instance.
   */
  kept: string[];
  stream: string;
}
/**
 * An instance with no `[forward]` block.
 */
export interface ForwardingUnconfigured {
  configured: false;
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
  from: string | null;
  to: string;
}
/**
 * `GET /api/level`: the level's flow numbers over a window.
 */
export interface Level {
  aging: LevelAging;
  arrivals: Arrival[];
  goal: string;
  history_s: number;
  level: LevelConfig;
  machine: string;
  now: number;
  orbit: LevelOrbit;
  sources: LevelSource[];
  throughput: HealthThroughput;
  time_in_state: LevelStay[];
  window_s: number;
  wip: LevelWip;
}
export interface LevelAging {
  runs: AgingRun[];
  threshold_s: number | null;
}
export interface AgingRun {
  age_s: number;
  over: boolean;
  source: string;
  state: string;
  task: string;
}
export interface Arrival {
  at: number;
  source: string;
  state: string;
}
/**
 * What the page needs of the level's config to draw it.
 */
export interface LevelConfig {
  activity: LevelActivity;
  facets: LevelFacet[];
  gates: string[];
  orbit: LevelOrbitConfig;
  runs: string;
  subject: string;
  terminals: LevelTerminal[];
  title: string;
}
export interface LevelActivity {
  measure: string;
  pace: string;
}
export interface LevelFacet {
  id: string;
  label: string;
}
export interface LevelOrbitConfig {
  suns: string;
  working: string[];
}
export interface LevelTerminal {
  id: string;
  role: string;
}
export interface LevelOrbit {
  suns: string;
  terminals: {
    [k: string]: OrbitTerminal;
  };
  working: {
    [k: string]: OrbitWorking;
  };
}
export interface OrbitTerminal {
  ended: number;
}
export interface OrbitWorking {
  task_s: number;
}
export interface LevelSource {
  dwell: {
    [k: string]: SourceDwell;
  };
  ended: {
    [k: string]: number;
  };
  id: string;
  shared: boolean;
  terminal_share: {
    [k: string]: number;
  };
  time_share: {
    [k: string]: number;
  };
  wip: number;
}
export interface SourceDwell {
  mean_s: number | null;
  task_s: number;
  visits: number;
}
export interface LevelStay {
  id: string;
  mean_s: number | null;
  task_s: number;
  visits: number;
}
export interface LevelWip {
  count: number;
  states: {
    [k: string]: number;
  };
}
/**
 * `GET /api/history?task=&flow=`: a task's path on one machine, and how many steps it has taken.
 */
export interface MachineHistory {
  flow: string;
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
  agents: RawAgent[];
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
   * Only the board machine: the skill flow each launching DAG starts.
   */
  launches?: {
    [k: string]: Launch;
  } | null;
  /**
   * Only the board machine: the state ids along its axis, in order (New to Done).
   */
  mainLine?: string[] | null;
  /**
   * The third party whose events move this machine ("GitHub"); absent for a machine StarPulse's own actors move.
   */
  source?: string | null;
  states: MachineState[];
  /**
   * The flows that open under this machine's states; the board's first is its In Progress delivery machine.
   */
  subflows?: SubFlow[] | null;
  transitions: Transition[];
  /**
   * Only the board machine: its writers per event.
   */
  writers?: {
    [k: string]: Writer[];
  } | null;
}
/**
 * A runs workflow's launch: the skill it starts and the flow that skill draws, null when it has none.
 */
export interface Launch {
  flow: string | null;
  skill: string;
}
export interface MachineState {
  final: boolean;
  id: string;
  initial: boolean;
  name: string;
}
/**
 * Where a Board state opens into another machine, and which Board event each inner final state fires.
 */
export interface SubFlow {
  exits: {
    [k: string]: string;
  };
  flow: string;
  /**
   * The flow the link opens under: `board`, or the flow whose `state` it hangs off.
   */
  parent: string;
  state: string;
  /**
   * What has to hold for the inner flow to run under `state`; empty when always.
   */
  when: string;
}
export interface Transition {
  event: string;
  source: string;
  target: string;
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
 * `declared` is a SubFlow on `machine`'s `state`; `observed` is the state the task held on `machine` when its session
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
 * `GET /api/merges`: the next page of merge rows, newest first, and whether older ones remain.
 */
export interface Merges {
  merges: LedgerRow[];
  more: boolean;
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
 * `GET /api/pulls`: the stored pull requests matching every filter given, by repository then number.
 */
export interface Pulls {
  pulls: PullRecord[];
}
/**
 * One pull request the PR store read from GitHub, as of `fetchedAt` (epoch seconds).
 */
export interface PullRecord {
  baseRefName: string;
  body: string;
  checks: "pass" | "failing" | "pending" | "none";
  fetchedAt: number;
  headRefOid: string;
  isDraft: boolean;
  mergeable: string;
  number: number;
  repo: string;
  requiredChecks: RequiredCheck[];
  state: "OPEN" | "MERGED" | "CLOSED";
  threads: number;
  updatedAt: string;
}
export interface RequiredCheck {
  name: string;
  result: "pass" | "failing" | "pending";
}
/**
 * `POST /api/move`: move `task` to the column `to`.
 */
export interface MoveRequest {
  actor?: string | null;
  session?: string | null;
  task: string;
  to: string;
}
/**
 * `POST /api/start`: start a session for `task` on `assignee`.
 */
export interface StartRequest {
  assignee: string;
  task: string;
}
/**
 * `POST /api/edit`: change fields of `task`; `base` holds the value each changed field had when the page read it.
 */
export interface EditRequest {
  base: {
    [k: string]: unknown;
  };
  changes: {
    [k: string]: unknown;
  };
  comment?: string | null;
  task: string;
}
/**
 * `POST /api/archive`: archive `task`, recording `reason` when it is not blank.
 */
export interface ArchiveRequest {
  reason?: string | null;
  task: string;
}
/**
 * `POST /api/tasks`: create a task in the board's starting lane.
 */
export interface CreateRequest {
  acceptanceCriteria?: string[] | null;
  assignee?: string | null;
  dependencies?: string[] | null;
  description?: string | null;
  labels?: string[] | null;
  milestone?: string | null;
  priority?: string | null;
  title: string;
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
 * `PUT /api/history-window`: set the shared history window.
 */
export interface WindowRequest {
  hours: number;
}
/**
 * `PUT /api/forwarding`: whether a person's name may leave the instance.
 */
export interface ForwardingRequest {
  opt_in: boolean;
}
/**
 * `POST /api/runs/events`: one workflow phase a producer reports.
 */
export interface RunEventRequest {
  depends?: string[] | null;
  phase: string;
  run_id: string;
  status: string;
  step?: string | null;
  time?: number | null;
  workflow: string;
}
/**
 * `POST /api/forward`: a batch of events an instance's forwarder sends a hub.
 */
export interface ForwardRequest {
  events: ForwardedEvent[];
  opt_in: boolean;
}
export interface ForwardedEvent {
  event_id: string;
  fields: {
    [k: string]: unknown;
  };
  stream: string;
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
   * The findings an engine posted that are still live.
   */
  insights?: Finding[] | null;
  /**
   * Each Ledger event's rows, newest first.
   */
  ledgers?: {
    [k: string]: LedgerRow[];
  } | null;
  machinePage?: MachinePage | null;
  machineStrip?: MachineStrip | null;
  /**
   * The pinned merge rows of the last day that the newest page leaves out.
   */
  mergePins?: LedgerRow[] | null;
  mergeStrip?: MergeStrip | null;
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
   * True while a just-started server is still reading its board: its Board is partial until a snapshot without it follows.
   */
  reading?: boolean | null;
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
 * A domain's DAGs, and whether each is declared safe to run from the page.
 */
export interface Domain {
  dags: DomainDag[];
  name: string;
}
export interface DomainDag {
  name: string;
  runSafe: boolean;
}
export interface FlowSnapshot {
  agents: RawAgent[];
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
 * `GET /api/task/<id>`: the full record of a task from the board's reader, keyed by its editable fields.
 */
export interface TaskRecord {
  record: {
    [k: string]: unknown;
  };
  task: string;
}
/**
 * `GET /api/level/trajectories`: the paths of the runs that ended in a terminal over a window.
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
 * `GET /api/level/what-if`: the chain with one transition's probability changed, from the usual first state.
 */
export interface WhatIf {
  chain: {
    [k: string]: ChainState;
  };
  ended: number;
  expected_days: Change;
  from: string;
  goal: string;
  history_s: number;
  machine: string;
  n: number;
  now: number;
  p: number;
  p_goal: Change;
  start: string;
  to: string;
  was: number;
  window_s: number;
}
export interface Change {
  after: number;
  before: number;
  change: number;
}
/**
 * `/api/history-window`: the effective window, the declared default, and whether Admin's override is in effect.
 */
export interface WindowState {
  default: number;
  hours: number;
  overridden: boolean;
}
