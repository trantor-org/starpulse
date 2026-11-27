/* Generated from starpulse/schemas/api.schema.json by pnpm run gen:types; edit starpulse/contracts/api/, not this file. */

export type JsonValue = unknown;

/**
 * The root of `api.schema.json`: every body as a property, so the generated types name each one.
 */
export interface ApiContract {
  adminState: AdminState;
  answers: (
    | Edited
    | Archived
    | Restored
    | Retired
    | TakenOver
    | Completed
    | Reopened
    | Dispatched
    | Parked
    | FreezeRequested
    | Created
    | CreatedEach
    | MachineWritten
    | MachineRetired
    | MilestoneCreated
    | MilestoneEdited
    | MilestoneArchived
    | DocCreated
    | DocEdited
    | DocArchived
    | Started
    | Accepted
    | ApiError
    | SkillRefusal
    | StaleEdit
    | WindowTooLong
    | Link
    | NotHolder
    | DeliveredElsewhere
    | UnrecognisedUrl
  )[];
  contractReport: ContractReport;
  dailyReports: DailyReports;
  docShown: DocShown;
  docs: Docs;
  donePage: DonePage;
  graphqlResponse: GraphqlResponse;
  harnesses: Harnesses;
  job: DagBody;
  jobs: Jobs;
  machineDetail: MachineDetail;
  machines: Machines;
  milestoneShown: MilestoneShown;
  milestones: Milestones;
  readyReport: ReadyReport;
  requests: (
    | StartRequest
    | StepsRequest
    | CreateRequest
    | TaskPutRequest
    | MilestoneCreateRequest
    | MachineCreateRequest
    | JobListRequest
    | MachineListRequest
    | MachinePutRequest
    | MilestoneListRequest
    | MilestonePutRequest
    | DocCreateRequest
    | DocListRequest
    | DailyReportListRequest
    | DocPutRequest
    | WindowRequest
    | GraphqlRequest
    | AdminRequest
  )[];
  retiredTasks: RetiredTasks;
  searchResults: SearchResults;
  snapshot: Snapshot;
  spend: Spend;
  taskRecord: TaskRecord;
  taskRecords: TaskRecords;
  trajectories: Trajectories;
  viewShown: ViewShown;
  windowState: WindowState;
  [k: string]: unknown;
}
/**
 * Admin's settings in one answer: the scheduler's status, then the display and theme choices.
 */
export interface AdminState {
  /**
   * Every gate holding admission back now, each with its use and limit; empty when none does.
   */
  blockedBy?: SchedulerBlock[];
  /**
   * Absent before the scheduler worker has reported them.
   */
  capacityLimits?: SchedulerCapacityLimits | null;
  dimensions: SchedulerDimension[];
  display: Display;
  enabled: boolean;
  /**
   * The latest kept rows of gate readings and block reasons, oldest first, kept by the scheduler itself.
   */
  gateHistory?: SchedulerGateRow[];
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
   * The stream position the state was read at: a `schedulerChanges` subscription from it misses no status change.
   */
  position: number;
  /**
   * Null when no window holds admission back.
   */
  quietHours?: QuietHours | null;
  sampledAt: number | null;
  /**
   * Absent before the scheduler worker has reported one.
   */
  sessionCap?: SchedulerSessionCap | null;
  /**
   * Each harness's in-flight count against its session cap; the Sessions meter follows `harness`.
   */
  sessionsByHarness?: {
    [k: string]: SchedulerHarnessSessions;
  };
  theme: Theme;
  [k: string]: unknown;
}
/**
 * One gate holding admission back: a capacity dimension the top task overfits, or `start-limit`, the session-start
 * service refusing every start because its live-session limit is full.
 */
export interface SchedulerBlock {
  /**
   * For `start-limit`, the refusals since a start last landed.
   */
  count?: number | null;
  limit: number;
  name: "cpu" | "memory" | "sessions" | "review" | "start-limit";
  use: number;
  [k: string]: unknown;
}
/**
 * The cpu and memory limits the scheduler admits against.
 */
export interface SchedulerCapacityLimits {
  cpu: SchedulerCapacityLimit;
  memory: SchedulerCapacityLimit;
  [k: string]: unknown;
}
/**
 * The cpu or memory limit in force, in percent, and where it comes from.
 */
export interface SchedulerCapacityLimit {
  /**
   * What `starpulse.toml` gives this dimension, which clearing the Admin limit returns to.
   */
  configLimit: number;
  limit: number;
  /**
   * `admin` when an operator set the limit in Admin, `starpulse.toml` when the config's limit holds.
   */
  source: "admin" | "starpulse.toml";
  [k: string]: unknown;
}
/**
 * One capacity dimension's use against its limit: percent for `cpu` and `memory`, a count for `sessions`, points for `review`.
 */
export interface SchedulerDimension {
  limit: number;
  name: "cpu" | "memory" | "sessions" | "review";
  use: number;
  [k: string]: unknown;
}
/**
 * How every device draws the page; a field left out of a write keeps its value.
 */
export interface Display {
  clock?: "24" | "12";
  density?: "comfortable" | "compact";
  /**
   * Off stills CSS animation and transitions and slows the Star Map's frame loop.
   */
  motion?: boolean;
  /**
   * The font size in percent of the design size, in steps of 5.
   */
  scale?: number;
  /**
   * The view an address with no `view` parameter opens.
   */
  view?: "constellation" | "kanban";
  [k: string]: unknown;
}
/**
 * One kept row of the gate history: every dimension's reading and every gate that held admission back at `at`.
 */
export interface SchedulerGateRow {
  /**
   * When the row was kept, in epoch seconds.
   */
  at: number;
  blockedBy: SchedulerBlock[];
  dimensions: SchedulerDimension[];
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * A task in the eligible lane that waits on the operator's decision rather than on capacity.
 */
export interface SchedulerOperatorTask {
  task: string;
  title: string;
  [k: string]: unknown;
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
   * `goes next`, `quiet hours` while the quiet hours hold admission, `<harness> usage limit` or `<harness> start halted: ...` while that harness is paused, or the first dimension the task overfits, which the strip shows after `waits:`.
   */
  reason: string;
  task: string;
  title: string;
  verdict: "starting" | "waits";
  [k: string]: unknown;
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
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * The session cap the selected harness runs under and where it comes from.
 */
export interface SchedulerSessionCap {
  /**
   * What `starpulse.toml` gives this harness, which clearing the Admin cap returns to.
   */
  configLimit: number;
  harness: string;
  limit: number;
  /**
   * `admin` when an operator set the cap in Admin, `starpulse.toml` when the config's limit holds.
   */
  source: "admin" | "starpulse.toml";
  [k: string]: unknown;
}
/**
 * One harness's scheduler sessions in flight against its own session cap.
 */
export interface SchedulerHarnessSessions {
  limit: number;
  use: number;
  [k: string]: unknown;
}
/**
 * The color pack and background every device draws in, built in or imported; a write replaces the whole theme.
 */
export interface Theme {
  /**
   * The id of the built-in background or of one in `bgs`.
   */
  bg?: string;
  bgs?: SavedBg[];
  /**
   * The id of a built-in pack or of one in `packs`.
   */
  pack?: string;
  packs?: SavedPack[];
  [k: string]: unknown;
}
/**
 * A background an operator imported; `n` is its neutral colors by name.
 */
export interface SavedBg {
  id: string;
  n: {
    [k: string]: string;
  };
  name: string;
  [k: string]: unknown;
}
/**
 * A color pack an operator imported.
 */
export interface SavedPack {
  id: string;
  pack: Pack;
  [k: string]: unknown;
}
/**
 * A color pack as the page builds it: `c` the role colors, `r` each role's derivation (a color, or a mix of two derivations), `x` any extra tokens.
 */
export interface Pack {
  c: {
    [k: string]: string;
  };
  name: string;
  r: {
    [k: string]: JsonValue;
  };
  src?: PackSource | null;
  vibe?: string | null;
  x?: {
    [k: string]: string;
  } | null;
  [k: string]: unknown;
}
export interface PackSource {
  label: string;
  [k: string]: unknown;
}
/**
 * An edit's answer: `advice` is what the board tells the mover about the task now it is edited, when it has any;
 * `warnings` are the lane rules an operator's move broke and landed.
 */
export interface Edited {
  advice?: string;
  changed: string[];
  task: string;
  warnings?: string[] | null;
  [k: string]: unknown;
}
/**
 * A task archive's answer: `requested` when an agent's archive of an open task only recorded the request.
 */
export interface Archived {
  requested: boolean;
  task: string;
  [k: string]: unknown;
}
export interface Restored {
  task: string;
  [k: string]: unknown;
}
export interface Retired {
  task: string;
  [k: string]: unknown;
}
export interface TakenOver {
  task: string;
  [k: string]: unknown;
}
export interface Completed {
  task: string;
  [k: string]: unknown;
}
export interface Reopened {
  task: string;
  [k: string]: unknown;
}
export interface Dispatched {
  session: string;
  task: string;
  [k: string]: unknown;
}
export interface Parked {
  task: string;
  to: string;
  [k: string]: unknown;
}
export interface FreezeRequested {
  request: "freeze" | "unfreeze";
  task: string;
  [k: string]: unknown;
}
export interface Created {
  task: string;
  [k: string]: unknown;
}
/**
 * A batch create's answer: each spec's new task, or why it was refused, in the order the specs came.
 */
export interface CreatedEach {
  results: (Created | SkillRefusal | ApiError)[];
  [k: string]: unknown;
}
/**
 * A refusal a skill satisfies: the skill that produces what the guard needs.
 */
export interface SkillRefusal {
  error: string;
  model?: string | null;
  schema?: {
    [k: string]: unknown;
  } | null;
  skill: string;
  [k: string]: unknown;
}
/**
 * Every refusal: what went wrong. A 400 for a body its request model refuses also names that `model` and the
 * JSON `schema` a valid value of the refused field meets.
 */
export interface ApiError {
  error: string;
  model?: string | null;
  schema?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
/**
 * `PUT /api/machines` and `PUT /api/machines/{name}`: the machine and the `hash` of the version now active.
 */
export interface MachineWritten {
  hash: string;
  machine: string;
  [k: string]: unknown;
}
export interface MachineRetired {
  machine: string;
  [k: string]: unknown;
}
export interface MilestoneCreated {
  milestone: string;
  [k: string]: unknown;
}
export interface MilestoneEdited {
  changed: string[];
  milestone: string;
  [k: string]: unknown;
}
export interface MilestoneArchived {
  milestone: string;
  [k: string]: unknown;
}
export interface DocCreated {
  doc: string;
  [k: string]: unknown;
}
export interface DocEdited {
  changed: string[];
  doc: string;
  [k: string]: unknown;
}
export interface DocArchived {
  doc: string;
  [k: string]: unknown;
}
export interface Started {
  at: number;
  task: string;
  url: string;
  [k: string]: unknown;
}
export interface Accepted {
  accepted: boolean;
  deprecated?: string | null;
  [k: string]: unknown;
}
/**
 * An edit refused because a field changed since the page read it: those fields with their current values.
 */
export interface StaleEdit {
  current: {
    [k: string]: unknown;
  };
  error: string;
  model?: string | null;
  schema?: {
    [k: string]: unknown;
  } | null;
  stale: string[];
  [k: string]: unknown;
}
/**
 * A level or telemetry window longer than its history, with the history's length.
 */
export interface WindowTooLong {
  error: string;
  history_s: number;
  model?: string | null;
  schema?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
/**
 * One stored link of a task, keyed by the task's UUID: `handle` is the task's current key, `url` the owning
 * adapter's display form of `ref` (None: it renders none), `requested_by` the session that asked, `at` when the
 * task actor wrote it and `event` the id of its `link-written` or `link-removed` event.
 */
export interface Link {
  at: string;
  event: string;
  handle: string;
  ref: string;
  requestedBy: string;
  role: "delivers" | "cites" | "holds";
  task: string;
  url?: string | null;
  [k: string]: unknown;
}
/**
 * A link request from a session that does not hold the task: the session, and the session that does (None: none).
 */
export interface NotHolder {
  error: string;
  holder?: string | null;
  model?: string | null;
  schema?: {
    [k: string]: unknown;
  } | null;
  session: string;
  [k: string]: unknown;
}
/**
 * A `delivers` link of a pull request that already delivers another task, named by UUID and current handle.
 */
export interface DeliveredElsewhere {
  error: string;
  handle: string;
  model?: string | null;
  ref: string;
  schema?: {
    [k: string]: unknown;
  } | null;
  task: string;
  [k: string]: unknown;
}
/**
 * A URL no configured forge adapter recognises: the URL and the adapter instances that were asked.
 */
export interface UnrecognisedUrl {
  adapters: string[];
  error: string;
  model?: string | null;
  schema?: {
    [k: string]: unknown;
  } | null;
  url: string;
  [k: string]: unknown;
}
/**
 * The contract checks `starpulse doctor` runs; `ok` is false when any fails.
 */
export interface ContractReport {
  checks: ContractCheck[];
  ok: boolean;
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * `POST /api/daily-reports`: the buckets of one machine's range, empty when it made no move in it.
 */
export interface DailyReports {
  items: DailyReportItem[];
  [k: string]: unknown;
}
/**
 * One bucket of a daily report: the transitions counted and the summed length of the Stays they ended.
 */
export interface DailyReportItem {
  bucket: string;
  count: number;
  seconds: number;
  [k: string]: unknown;
}
/**
 * `GET /api/docs/<id>`: one doc, archived or open.
 */
export interface DocShown {
  doc: DocRecord;
  [k: string]: unknown;
}
/**
 * A doc as the board's reader gives it: the summary and the text after its front matter.
 */
export interface DocRecord {
  /**
   * The doc was archived: read from the archive, off the open ones.
   */
  archived?: boolean;
  body: string;
  created_date: string;
  id: string;
  path: string;
  /**
   * What a `PUT /api/docs/{id}` names as its `base` to write only over this record.
   */
  revision: string;
  title: string;
  type: string;
  updated_date: string;
  [k: string]: unknown;
}
/**
 * `POST /api/docs`: the named docs, without bodies, in the order asked.
 */
export interface Docs {
  docs: DocSummary[];
  [k: string]: unknown;
}
/**
 * A doc as the board's lister gives it: its front matter and where it is filed, without its body.
 */
export interface DocSummary {
  /**
   * The doc was archived: read from the archive, off the open ones.
   */
  archived?: boolean;
  created_date: string;
  id: string;
  path: string;
  title: string;
  type: string;
  updated_date: string;
  [k: string]: unknown;
}
/**
 * `GET /api/done`: the next page of done tasks past their hot day, newest first, and whether older ones remain.
 */
export interface DonePage {
  more: boolean;
  tasks: RawTask[];
  [k: string]: unknown;
}
/**
 * A Backlog task. On the board its state is its lane; on every other machine, the state its latest machine event left it in.
 */
export interface RawTask {
  active?: number | null;
  /**
   * Why a Board task needs an ADR; empty or absent when it needs none.
   */
  adr_needed?: string | null;
  /**
   * The session that last claimed a Board task; empty when none has, absent off the Board.
   */
  assignee?: string | null;
  /**
   * When a Board task was created, in epoch seconds; null or absent when unknown.
   */
  created?: number | null;
  /**
   * A Board task's acceptance criteria in file order; absent off the Board.
   */
  criteria?: TaskCriterion[] | null;
  /**
   * A Board task's Definition of Done items in file order; absent off the Board.
   */
  definition_of_done?: TaskCriterion[] | null;
  /**
   * A task's pull requests it has a `delivers` link to.
   */
  delivered?: string[] | null;
  /**
   * A task's dependencies, as task ids.
   */
  dependencies?: string[] | null;
  /**
   * A task's Backlog description.
   */
  description?: string | null;
  /**
   * How a Board task's duplicate search resolved its candidates; empty or absent when none.
   */
  duplicate_resolution?: string | null;
  /**
   * The queries a Board task's duplicate search ran; empty or absent when none.
   */
  duplicate_search?: string | null;
  /**
   * When a Board task entered its lane, epoch seconds; absent when the server holds no time for it.
   */
  entered?: number | null;
  /**
   * The id of the finished task a Board task follows up; empty or absent when none.
   */
  follows?: string | null;
  /**
   * The freeze the task actor holds the task in; no move of it lands until it is lifted.
   */
  frozen?: Frozen | null;
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
   * The verdict on each Board column the task may move to, by state id; a snapshot keeps it for an active task only.
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
   * A task's pull requests: the pages of the changes it has a `delivers` or `cites` link to.
   */
  prs?: string[] | null;
  /**
   * The first `readable` guard rule a Board task's description breaks, with its line; empty when it reads well, absent off the Board.
   */
  readable?: string | null;
  /**
   * The claim-TTL release a Board task's claim ended in; null when none ended it.
   */
  released?: ClaimRelease | null;
  /**
   * A task's scheduler runs: those whose run id names it (`dag-run-task-<N>-<ts>`).
   */
  runs?: TaskRun[] | null;
  /**
   * What a held In Progress task's holder session is doing; absent off that lane or when unheld.
   */
  session_activity?: SessionActivity | null;
  /**
   * The skill machine an In Progress task is held in; absent off the held view.
   */
  skill?: HeldSkill | null;
  /**
   * The key the producer filed a Board task under (`task create --source`); empty or absent when none.
   */
  source?: string | null;
  state: string;
  steps?: number | null;
  /**
   * A machine's task: the id of the Backlog task its events name.
   */
  task?: string | null;
  /**
   * A Board task's tier (regression, bug, leverage, standard or decide); absent on a row an adapter does not tier.
   */
  tier?: string | null;
  title: string;
  /**
   * A machine task's steps, as points indexing the `names` of the flow or move delta.
   */
  trail?: ([unknown, unknown, unknown] | [unknown, unknown, unknown, unknown])[] | null;
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
  [k: string]: unknown;
}
/**
 * One acceptance criterion of a Board task and whether it is checked.
 */
export interface TaskCriterion {
  checked: boolean;
  text: string;
  [k: string]: unknown;
}
/**
 * The freeze the task actor holds a task in: who asked, when and why.
 */
export interface Frozen {
  at: string;
  by: string;
  reason: string;
  [k: string]: unknown;
}
/**
 * The verdict on moving a task to one column: allowed, or guarded by a declared rule.
 */
export interface Move {
  /**
   * The verdict for an actor a guard treats apart from the rest, such as one it exempts or warns, by actor; any other actor meets the move's own.
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
   * The lane rules the move breaks that the actor is warned of and may still make.
   */
  warnings?: RuleBreak[];
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
  /**
   * The lane rules the move breaks that this actor is warned of and may still make, each with its skill.
   */
  warnings?: RuleBreak[];
}
/**
 * One board rule a move breaks: what it needs and the skill that produces it.
 */
export interface RuleBreak {
  /**
   * What the broken rule needs.
   */
  reason: string;
  /**
   * The skill that produces what the rule needs; empty when none.
   */
  skill?: string;
}
/**
 * The claim a Board task's claim-TTL sweep, or its idle holder's release, ended: when, and the session, last renewal and TTL.
 */
export interface ClaimRelease {
  /**
   * When the release was recorded, epoch seconds.
   */
  at: number;
  /**
   * The task actor ended this claim because its holder sat idle, not the TTL sweep.
   */
  idle?: boolean;
  /**
   * The session's last renewal before the release, epoch seconds.
   */
  last_renewal: number;
  session: string;
  /**
   * The claim TTL, in seconds, the session missed.
   */
  ttl: number;
  [k: string]: unknown;
}
/**
 * One scheduler run a task's id names, linked to the run's own page.
 */
export interface TaskRun {
  startedAt: string;
  status: string;
  url: string;
  [k: string]: unknown;
}
/**
 * What a held working task's holder session is doing, read from its transcript when the snapshot is drawn.
 */
export interface SessionActivity {
  /**
   * Seconds idle when the snapshot was drawn; present only when idle.
   */
  idle_s?: number | null;
  /**
   * The holder session's latest assistant message with text, cut to 2000 characters with an ellipsis; absent when it has not reported.
   */
  last_message?: string | null;
  /**
   * When `last_message` was written, ISO 8601; present with it.
   */
  last_message_at?: string | null;
  /**
   * When the session's last turn was written, ISO 8601; absent when unknown.
   */
  last_turn_at?: string | null;
  /**
   * `working` mid-turn, `idle` after a finished turn, `unknown` when no running session with a transcript holds the task.
   */
  state: "working" | "idle" | "unknown";
  [k: string]: unknown;
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
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * `POST /graphql`: the data the query asked for, and the errors it met; a query the schema refuses has errors only.
 */
export interface GraphqlResponse {
  data?: {
    [k: string]: unknown;
  } | null;
  errors?: GraphqlError[] | null;
  [k: string]: unknown;
}
/**
 * One error a query met, as the GraphQL over HTTP spec names its fields.
 */
export interface GraphqlError {
  /**
   * Machine-readable detail; `code` is `REREAD` for a lost stream position.
   */
  extensions?: {
    [k: string]: unknown;
  } | null;
  locations?:
    | {
        [k: string]: number;
      }[]
    | null;
  message: string;
  path?: (string | number)[] | null;
  [k: string]: unknown;
}
/**
 * `GET /api/harnesses`: the tiers in order and each harness with its models and efforts.
 */
export interface Harnesses {
  harnesses: HarnessBody[];
  tiers: string[];
  [k: string]: unknown;
}
export interface HarnessBody {
  label: string;
  name: string;
  reason: string | null;
  sessions: boolean;
  tiers: {
    [k: string]: HarnessTier;
  };
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * A runs workflow as the page draws it: the latest run, the runs in flight and the pool it runs on.
 */
export interface DagBody {
  /**
   * Every running or queued run of the workflow, including concurrent ones.
   */
  active?: ActiveRun[] | null;
  /**
   * The newest closed runs of the workflow of any status, newest first; absent when none ran.
   */
  closed?: RecentRun[] | null;
  /**
   * The newest failed runs of the workflow, newest first; absent when none failed.
   */
  failed?: RecentRun[] | null;
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
  /**
   * The runner's own start page for the workflow; empty when its runner has none.
   */
  startUrl: string;
  startedAt: string;
  /**
   * The workflow's runs over the last seven days; None when it never ran or they are unknown.
   */
  stats: RunStats | null;
  status: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
  steps: Step[];
  [k: string]: unknown;
}
/**
 * One run of a DAG that is running or queued now.
 */
export interface ActiveRun {
  /**
   * The attempt of the step the run is on (or failed on); None when the engine counts none.
   */
  attempt?: number | null;
  /**
   * The commit the run built, as the engine names it; None when it names none.
   */
  commit?: string | null;
  /**
   * The last failure's message (the step's, or the run's); None when nothing failed.
   */
  failure?: string | null;
  /**
   * The pull request the run was started for; None when it was not started for one.
   */
  pr?: number | null;
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
  /**
   * The Board task the run works on (`TASK-N`); None when it names none.
   */
  task?: string | null;
  /**
   * A link to the run in the scheduler's own page; empty when it has none.
   */
  url?: string;
}
/**
 * One run of a DAG within the last day, running or over, with the parameters it started with.
 */
export interface RecentRun {
  /**
   * The attempt of the step the run is on (or failed on); None when the engine counts none.
   */
  attempt?: number | null;
  /**
   * The commit the run built, as the engine names it; None when it names none.
   */
  commit?: string | null;
  /**
   * The last failure's message (the step's, or the run's); None when nothing failed.
   */
  failure?: string | null;
  /**
   * When the run ended, ISO 8601 UTC; empty while it runs.
   */
  finishedAt: string;
  /**
   * The `KEY=value` parameters the run started with, by name; empty when it had none.
   */
  params: {
    [k: string]: string;
  };
  /**
   * The pull request the run was started for; None when it was not started for one.
   */
  pr?: number | null;
  /**
   * The engine's own status for the run when it differs from `status`, shown as is.
   */
  raw?: string | null;
  /**
   * The run's id.
   */
  runId: string;
  /**
   * When the run started, ISO 8601 UTC (`2026-10-02T17:00:00Z`).
   */
  startedAt: string;
  /**
   * The run's status.
   */
  status: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
  /**
   * Each step the run reached by name with its status in this run.
   */
  steps: {
    [k: string]: "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";
  };
  /**
   * The Board task a `dag-run-task-<N>-<ts>` run id names (`TASK-N`); None for any other run.
   */
  task?: string | null;
  /**
   * A link to the run in the scheduler's own page; empty when it has none.
   */
  url?: string;
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
 * `POST /api/jobs`: every runs workflow as the snapshot lists it, with the domains, cues, pools and the error a runs
 * instance reported, and the stream position the list was read at: a `jobChanges` subscription from it carries every
 * change after.
 */
export interface Jobs {
  /**
   * The DAGs cued by a Board event.
   */
  cues: Cue[];
  /**
   * The DAG domains the config declares.
   */
  domains: Domain[];
  error: string | null;
  items: DagBody[];
  /**
   * The concurrency pools the DAGs run on, each named `<instance>/<pool>`.
   */
  pools: Pool[];
  position: number;
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * A domain's DAGs; `processes` package them when configured.
 */
export interface Domain {
  dags: DomainDag[];
  name: string;
  processes?: DomainProcess[];
  [k: string]: unknown;
}
export interface DomainDag {
  name: string;
  [k: string]: unknown;
}
/**
 * A named package of a domain's DAGs.
 */
export interface DomainProcess {
  dags: DomainDag[];
  name: string;
  [k: string]: unknown;
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
/**
 * `GET /api/machines/{name}`: one machine's declared config. `skill` is the one its first parent link runs it with
 * (empty when none names one); `lanes` is each lane's surface by lane name, on the Board machine only; `hash` is the
 * version the store runs it under, the `base` of a write, and absent when the store holds none.
 */
export interface MachineDetail {
  hash?: string | null;
  lanes?: {
    [k: string]: LaneSurface;
  } | null;
  launches: {
    [k: string]: Launch;
  };
  name: string;
  parents: string[];
  skill: string;
  submachines: Submachine[];
  type: string | null;
  [k: string]: unknown;
}
/**
 * What a session holding the lane may call: its tools, its exit tools and the skill bound on entry.
 */
export interface LaneSurface {
  exits: ExitTool[];
  skill: string | null;
  tools: string[];
  [k: string]: unknown;
}
/**
 * A typed exit tool of a lane: the event it fires and the JSON schema of its arguments.
 */
export interface ExitTool {
  event: string;
  name: string;
  schema: {
    [k: string]: unknown;
  };
  to: string;
  [k: string]: unknown;
}
/**
 * A runs workflow's launch: the skill it starts and the machine that skill draws, null when it has none.
 */
export interface Launch {
  machine: string | null;
  skill: string;
  [k: string]: unknown;
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
  /**
   * Inner event to the Board event it fires; empty when the link routes none.
   */
  routes?: {
    [k: string]: string;
  };
  /**
   * The skill a session runs while the inner machine does; empty when the link names none.
   */
  skill?: string;
  state: string;
  /**
   * What has to hold for the inner machine to run under `state`; empty when always.
   */
  when: string;
  [k: string]: unknown;
}
/**
 * `POST /api/machines`: every machine the board draws.
 */
export interface Machines {
  machines: MachineListed[];
  [k: string]: unknown;
}
/**
 * A machine of `POST /api/machines`: the machine as the snapshot draws it, with its name, its `type`, the
 * machines it is a submachine of and the `roles` of its states.
 */
export interface MachineListed {
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
  name: string;
  /**
   * The edge a finished skill hands to; null when the machine declares none.
   */
  next?: HeldNext | null;
  parents: string[];
  roles: Roles;
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
  type: string | null;
  /**
   * Its YAML-declared writers per event.
   */
  writers?: {
    [k: string]: Writer[];
  } | null;
  [k: string]: unknown;
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
   * The open lanes the kanban and the Star Map draw, in the machine's order: every State but the initial and final.
   */
  lanes?: string[];
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
   * Where a merged task rests while its post-merge QA runs.
   */
  verifying?: string | null;
  /**
   * Where a task waits on its Start Criteria or dependencies.
   */
  waiting?: string | null;
  /**
   * Where a session works a task.
   */
  working?: string | null;
  [k: string]: unknown;
}
export interface MachineState {
  final: boolean;
  id: string;
  initial: boolean;
  name: string;
  /**
   * Which state wins when a task's dependencies would put it in more than one: the higher number wins, a tie keeps the task where it is.
   */
  priority?: number;
  /**
   * The type the machine declares the state: `initial`, `final`, `resting`, `waiting_on_fact` or `waiting_on_person`; null when it declares none.
   */
  role?: string | null;
  [k: string]: unknown;
}
export interface Transition {
  /**
   * The skill sentence that authorizes the transition; absent when its YAML cites none.
   */
  cite?: Cite | null;
  event: string;
  source: string;
  target: string;
  [k: string]: unknown;
}
/**
 * The sentence of a skill that sends a session down a transition.
 */
export interface Cite {
  quote: string;
  skill: string;
  [k: string]: unknown;
}
/**
 * Who fires a Board event: a runs workflow (by `<instance>/<workflow>` name), `operator` or `agent`.
 */
export interface Writer {
  actor: string;
  trigger: string;
  [k: string]: unknown;
}
/**
 * `GET /api/milestones/<id>`: one milestone, archived or open.
 */
export interface MilestoneShown {
  milestone: MilestoneRecord;
  [k: string]: unknown;
}
/**
 * A milestone as the board's reader gives it: its sections as text and bullet lists, and its whole description.
 */
export interface MilestoneRecord {
  adrs: string[];
  /**
   * The milestone was archived: read from the archive, off the open ones.
   */
  archived?: boolean;
  description: string;
  id: string;
  outcome: string;
  retro: string;
  /**
   * What a `PUT /api/milestones/{id}` names as its `base` to write only over this record.
   */
  revision: string;
  specs: string[];
  title: string;
  [k: string]: unknown;
}
/**
 * `POST /api/milestones`: every open milestone, by ascending number.
 */
export interface Milestones {
  milestones: MilestoneRecord[];
  [k: string]: unknown;
}
/**
 * Whether the server can serve the board; `components` names `store`, `board`, `writer` and `contexts`, and the route
 * answers 503 with this body when any is not ready.
 */
export interface ReadyReport {
  components: {
    [k: string]: ReadyComponent;
  };
  ready: boolean;
  [k: string]: unknown;
}
/**
 * One part of the server `/api/health` judges.
 */
export interface ReadyComponent {
  detail: string;
  ready: boolean;
  [k: string]: unknown;
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
 * `POST /api/steps`: the seconds each step of one `command` run took, and its reuse hit or miss.
 *
 * `steps` names at most 100 steps (`[a-z0-9_.:-]`, 64 characters) with their seconds; `outcome` is how the run ended.
 */
export interface StepsRequest {
  command: string;
  outcome: "ok" | "failed";
  reuse?: ("hit" | "miss") | null;
  steps?: {
    /**
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^[a-z0-9_.:-]{1,64}$".
     */
    [k: string]: number;
  };
}
/**
 * `PUT /api/tasks`: create a task in the lane `status` names or else the board's starting lane, stamped
 * `created_by: <harness>:<session>`, or each of `tasks` in one call, each with its own title and details.
 */
export interface CreateRequest {
  acceptanceCriteria?: string[] | null;
  actor?: string | null;
  adrNeeded?: string | null;
  assignee?: string | null;
  /**
   * Tasks that gain the new task as a dependency.
   */
  blocks?: string[] | null;
  brief?: Brief | null;
  /**
   * Answer the duplicate search's record and file nothing.
   */
  checkDuplicates?: boolean;
  definitionOfDone?: string[] | null;
  dependencies?: string[] | null;
  documentation?: string[] | null;
  /**
   * Words to search the board for a task that does this work: the server searches them, the citations in the text and its meaning, and records what it finds as `duplicateSearch`.
   */
  duplicateQueries?: string[] | null;
  duplicateResolution?: string | null;
  duplicateSearch?: string | null;
  follows?: string | null;
  harness?: string | null;
  impact?: string | null;
  labels?: string[] | null;
  members?: {
    [k: string]: MemberKindSize;
  } | null;
  milestone?: string | null;
  notes?: string | null;
  priority?: string | null;
  profile?: string | null;
  ref?: string | null;
  references?: string[] | null;
  /**
   * The client's key for this send: a create sent again with it answers the first send's answer.
   */
  request_key?: string | null;
  session?: string | null;
  size?: string | null;
  skill?: string | null;
  source?: string | null;
  status?: string | null;
  task?: string | null;
  tasks?: [CreateSpec, ...CreateSpec[]] | null;
  tier?: string | null;
  title?: string | null;
  type?: string | null;
  urgency?: string | null;
}
/**
 * A task's description as fields; `rollback` is required when `blast_radius.undo` is 2 or more.
 */
export interface Brief {
  blast_radius: BlastRadius;
  cited?: string[] | null;
  current_state: string;
  example?: string | null;
  open_questions?: string[] | null;
  /**
   * @minItems 1
   */
  out_of_scope: [string, ...string[]];
  outcome: string;
  rollback?: string | null;
  /**
   * @minItems 1
   */
  scope: [string, ...string[]];
  /**
   * @minItems 1
   */
  stop_conditions: [string, ...string[]];
  terms?: Term[] | null;
  why: string;
}
/**
 * The four scores, each 0 to 3, and the sentence on the worst axis.
 */
export interface BlastRadius {
  data: number;
  detect: number;
  note: string;
  reach: number;
  undo: number;
}
export interface Term {
  meaning: string;
  term: string;
}
/**
 * One batch member's kind and size, each without its label prefix.
 */
export interface MemberKindSize {
  kind: string;
  size: string;
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
  adrNeeded?: string | null;
  assignee?: string | null;
  /**
   * Tasks that gain the new task as a dependency.
   */
  blocks?: string[] | null;
  brief: Brief;
  /**
   * Answer the duplicate search's record and file nothing.
   */
  checkDuplicates?: boolean;
  definitionOfDone?: string[] | null;
  dependencies?: string[] | null;
  documentation?: string[] | null;
  /**
   * Words to search the board for a task that does this work: the server searches them, the citations in the text and its meaning, and records what it finds as `duplicateSearch`.
   */
  duplicateQueries?: string[] | null;
  duplicateResolution?: string | null;
  duplicateSearch?: string | null;
  follows?: string | null;
  impact?: string | null;
  labels?: string[] | null;
  members?: {
    [k: string]: MemberKindSize;
  } | null;
  milestone?: string | null;
  notes?: string | null;
  priority?: string | null;
  profile?: string | null;
  ref?: string | null;
  references?: string[] | null;
  size?: string | null;
  skill?: string | null;
  source?: string | null;
  status?: string | null;
  task?: string | null;
  tier?: string | null;
  title: string;
  type?: string | null;
  urgency?: string | null;
}
/**
 * `PUT /api/tasks/{id}`: write the task over the `base` it read, or reopen, complete, restore, retire, take it over, park
 * it, ask the task actor to freeze or unfreeze it or dispatch a session to it.
 *
 * An edit names `changes` (and `base`, the value each changed field had when read) or a `comment`. `changes` that
 * name only an `assignee` dispatch that session to the task, which the task actor pins; the `base` assignee is the
 * holder, found dead, whose lease the dispatch ends first. Otherwise the
 * body names exactly one of `reopen` (the Done task goes back to In Progress, with this reason), `completed: true`
 * (the Done task moves into the board's completed tasks), `archived: false` (the archived task returns to the
 * board), `retired: true` (the finished task goes off the board into the history store's retired tasks),
 * `interactive: true` (the unattended task is taken over), `park` (the held task pauses for the one
 * reason it names, with the `comment` beside it), `freeze` (the task actor freezes the task in its lane, for this
 * reason) and `unfreeze: true` (the task actor lifts the freeze; only the operator or the freezer may ask it).
 */
export interface TaskPutRequest {
  actor?: string | null;
  archived?: false | null;
  base?: EditBase;
  breakGlass?: boolean;
  changes?: Changes;
  comment?: string | null;
  completed?: true | null;
  freeze?: string | null;
  harness?: string | null;
  interactive?: true | null;
  park?: Park | null;
  reopen?: string | null;
  request_key?: string | null;
  retired?: true | null;
  session?: string | null;
  unfreeze?: true | null;
}
/**
 * The value each changed field had when the caller read it, a field the record holds as it holds it: a field the
 * edit does not change may be named or left out.
 */
export interface EditBase {
  acceptanceCriteria?: ChecklistItem[];
  actorMemory?: {
    [k: string]: JsonValue;
  };
  adrNeeded?: string;
  assignee?: string;
  definitionOfDone?: ChecklistItem[];
  dependencies?: string[];
  dependencyNeeds?: string[];
  description?: string;
  documentation?: string[];
  duplicateResolution?: string;
  duplicateSearch?: string;
  finalSummary?: string;
  follows?: string;
  frozen?: FrozenEdit;
  impact?: string;
  labels?: string[];
  members?: {
    [k: string]: MemberKindSize;
  };
  milestone?: string;
  modifiedFiles?: string[];
  needsAttention?: string;
  notes?: string;
  plan?: string;
  priority?: string;
  profile?: string;
  references?: string[];
  source?: string;
  status?: string;
  tier?: string;
  title?: string;
  type?: string;
  urgency?: string;
  [k: string]: unknown;
}
/**
 * One acceptance criterion or definition-of-done item; an item without `n` is numbered after the highest given.
 */
export interface ChecklistItem {
  checked: boolean;
  n?: number;
  text: string;
}
/**
 * Who froze the task, when and why.
 */
export interface FrozenEdit {
  at?: string | number | null;
  by?: string | null;
  reason?: string | null;
}
/**
 * An edit's fields by name, each as the board's writer takes it. `documentation` entries are links; `appendNotes`
 * adds to the notes as they are when the write lands, and `planReason` is why the plan changes: neither has a base.
 */
export interface Changes {
  acceptanceCriteria?: ChecklistItem[];
  actorMemory?: {
    [k: string]: JsonValue;
  };
  adrNeeded?: string;
  appendNotes?: string;
  assignee?: string;
  brief?: Brief;
  definitionOfDone?: ChecklistItem[];
  dependencies?: string[];
  dependencyNeeds?: string[];
  description?: string;
  documentation?: string[] | null;
  duplicateResolution?: string;
  duplicateSearch?: string;
  finalSummary?: string;
  follows?: string;
  frozen?: FrozenEdit;
  impact?: string;
  labels?: string[];
  members?: {
    [k: string]: MemberKindSize;
  };
  milestone?: string;
  modifiedFiles?: string[];
  needsAttention?: string;
  notes?: string;
  plan?: string;
  planReason?: string;
  priority?: string;
  profile?: string;
  references?: string[];
  source?: string;
  status?: string;
  tier?: string;
  title?: string;
  type?: string;
  urgency?: string;
}
/**
 * Pause the task on exactly one reason, which picks the lane: `untilTask` (tasks that must reach Done, or
 * `TASK-N#K` for one open criterion of a task) and `until` (event subjects an alert or a deploy emits) wait;
 * `operator` (what only the operator can do) needs attention.
 */
export interface Park {
  operator?: string | null;
  until?: string[] | null;
  untilTask?: string[] | null;
}
/**
 * `PUT /api/milestones`: open a milestone; only the title is required.
 */
export interface MilestoneCreateRequest {
  adrs?: string[] | null;
  outcome?: string | null;
  retro?: string | null;
  specs?: string[] | null;
  title: string;
}
/**
 * `PUT /api/machines`: create a machine from `definition`, a machine document, when no active machine has its name.
 */
export interface MachineCreateRequest {
  definition: MachineDefinition;
}
/**
 * A machine document: its states, the events that move a task between them, and what it declares around them.
 */
export interface MachineDefinition {
  bindings?: {
    [k: string]: string;
  } | null;
  cues?: [MachineCue, ...MachineCue[]] | null;
  events: {
    /**
     * @minItems 1
     *
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^[A-Za-z][A-Za-z0-9_]*$".
     */
    [k: string]: [MachineTransition, ...MachineTransition[]];
  };
  launches?: {
    [k: string]: MachineLaunch;
  } | null;
  main_line?: [string, ...string[]] | null;
  migrations?: {
    /**
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^[a-z][a-z0-9_]*$".
     */
    [k: string]: string;
  } | null;
  name: string;
  next?: MachineNext | null;
  parents?: string[] | null;
  rests?: [string, ...string[]] | null;
  source?: string | null;
  states: {
    [k: string]: MachineState1;
  };
  submachines?: [MachineSubmachine, ...MachineSubmachine[]] | null;
  tiers?: [[string, ...string[]], ...[string, ...string[]][]] | null;
  type?: ("machine" | "phase machine" | "sub-machine") | null;
  writers?: {
    /**
     * @minItems 1
     *
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^[A-Za-z][A-Za-z0-9_]*$".
     */
    [k: string]: [MachineWriter, ...MachineWriter[]];
  } | null;
}
export interface MachineCue {
  dag: string;
  event: string;
  grace?: number | null;
  on: string;
  resolves: "forced" | "next";
}
export interface MachineTransition {
  cite?: MachineCite | null;
  from: string | [string, ...string[]];
  if?: MachineGuard | null;
  to: string;
  unless?: MachineGuard | null;
}
export interface MachineCite {
  quote: string;
  skill: string;
}
export interface MachineGuard {
  when: {
    [k: string]: EventMatch;
  };
}
/**
 * How one event field is matched: exactly one of `equals`, `in` and `exists`.
 *
 * This interface was referenced by `undefined`'s JSON-Schema definition
 * via the `patternProperty` "^[A-Za-z_][A-Za-z0-9_]*$".
 */
export interface EventMatch {
  equals?: boolean | number | number | string | null;
  exists?: boolean | null;
  in?: [boolean | number | number | string, ...(boolean | number | number | string)[]] | null;
}
export interface MachineLaunch {
  machine?: string | null;
  skill: string;
}
export interface MachineNext {
  kind: "skill" | "operation";
  name: string;
}
/**
 * This interface was referenced by `undefined`'s JSON-Schema definition
 * via the `patternProperty` "^[a-z][a-z0-9_]*$".
 */
export interface MachineState1 {
  aliases?: string[] | null;
  final?: boolean | null;
  initial?: boolean | null;
  label?: string | null;
  priority?: number | null;
  role?: ("resting" | "waiting_on_fact" | "waiting_on_person") | null;
}
export interface MachineSubmachine {
  exits: {
    /**
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^[a-z][a-z0-9_]*$".
     */
    [k: string]: string;
  };
  machine: string;
  routes?: {
    /**
     * This interface was referenced by `undefined`'s JSON-Schema definition
     * via the `patternProperty` "^[a-z][a-z0-9_]*$".
     */
    [k: string]: string;
  } | null;
  skill?: string | null;
  state: string;
  when?: string | null;
}
export interface MachineWriter {
  actor: string;
  trigger: string;
}
/**
 * `POST /api/jobs`: list the workflows the runs adapters report. It takes no field.
 */
export interface JobListRequest {}
/**
 * `POST /api/machines`: list the machines the board draws. It takes no field.
 */
export interface MachineListRequest {}
/**
 * `PUT /api/machines/{name}`: activate `definition`, a machine document named `name`, over the version `base` (the
 * `hash` of the machine detail the caller read). `policy`, the table rows of the whole board policy, is written and
 * activated with it.
 */
export interface MachinePutRequest {
  base: string;
  definition: MachineDefinition;
  policy?: PolicyRows | null;
}
/**
 * The table rows of the whole board policy; a table left out holds no row.
 */
export interface PolicyRows {
  exits?: PolicyExit[];
  lanes?: PolicyLane[];
  profiles?: PolicyProfile[];
  routes?: PolicyRoute[];
  rules?: PolicyRule[];
  tools?: PolicyTool[];
  vocabularies?: PolicyVocabulary[];
  watches?: PolicyWatch[];
}
export interface PolicyExit {
  actor: string;
  event: string;
  trigger: string;
}
export interface PolicyLane {
  label?: string | null;
  name: string;
  position: number;
  role: string | null;
  skill?: string | null;
}
export interface PolicyProfile {
  kind: string;
  profile: string;
  size: number;
}
export interface PolicyRoute {
  condition?: {
    [k: string]: JsonValue;
  } | null;
  event: string;
  source: string;
  target: string;
}
export interface PolicyRule {
  on: {
    [k: string]: JsonValue;
  };
  position: number;
  reason: string;
  require: {
    [k: string]: JsonValue;
  };
  skill: string;
  unless_actor: string[];
}
export interface PolicyTool {
  lane: string;
  tool: string;
}
export interface PolicyVocabulary {
  name: string;
  position: number;
  value: string;
}
export interface PolicyWatch {
  event: string;
  fact: string;
  lane: string;
  position: number;
}
/**
 * `POST /api/milestones`: list the open milestones. It takes no field.
 */
export interface MilestoneListRequest {}
/**
 * `PUT /api/milestones/{id}`: replace the `title`, `outcome`, `specs`, `adrs` or `retro` named, if the milestone
 * still reads `base`, the `revision` of the record the caller read.
 */
export interface MilestonePutRequest {
  adrs?: string[] | null;
  base: string;
  outcome?: string | null;
  retro?: string | null;
  specs?: string[] | null;
  title?: string | null;
}
/**
 * `PUT /api/docs`: file a doc; only the title is required. `type` is `specification`, `guide`, `readme`, `postmortem` or `other`; `extension` (default `md`) is the file's type.
 */
export interface DocCreateRequest {
  body?: string | null;
  extension?: string | null;
  folder?: string | null;
  title: string;
  type?: string | null;
}
/**
 * `POST /api/docs`: list the docs `ids` names, bodies left out.
 */
export interface DocListRequest {
  ids: string[];
}
/**
 * `POST /api/daily-reports`: one machine's counts and summed durations over a range of days, read from the daily
 * report rows, `limit` buckets from `offset`.
 */
export interface DailyReportListRequest {
  filter: DailyReportFilter;
  limit?: number;
  offset?: number;
}
/**
 * The `filter` of `POST /api/daily-reports`: `machine`, `since` and `until` (inclusive local dates in
 * America/Phoenix) are required, `state` keeps the transitions out of that state, and `bucket` sums the rows per `day`,
 * `month`, `year` or the whole `range`.
 */
export interface DailyReportFilter {
  bucket?: "day" | "month" | "year" | "range";
  machine?: string | null;
  since?: string | null;
  state?: string | null;
  until?: string | null;
}
/**
 * `PUT /api/docs/{id}`: replace the `title`, `type` or `body` named, if the doc still reads `base`, the `revision`
 * of the record the caller read. `archived: false` first returns an archived doc to `folder` under the board's docs
 * (the docs folder itself when absent), unchanged; a `folder` on an open doc moves it there.
 */
export interface DocPutRequest {
  archived?: false | null;
  base: string;
  body?: string | null;
  folder?: string | null;
  title?: string | null;
  type?: string | null;
}
/**
 * `PUT /api/history-window`: set the shared history window.
 */
export interface WindowRequest {
  hours: number;
}
/**
 * `POST /graphql`: one GraphQL document and the operation of it to run.
 */
export interface GraphqlRequest {
  /**
   * The operation of the document to run.
   */
  operationName?: string | null;
  /**
   * The GraphQL document: a fragment and the named queries a view stores.
   */
  query: string;
  /**
   * The values of the operation's variables.
   */
  variables?: {
    [k: string]: JsonValue;
  } | null;
}
/**
 * `PUT /api/admin`: any of the scheduler's settings, a patch of the display choices and/or a whole theme; a field
 * left out keeps its value.
 */
export interface AdminRequest {
  /**
   * The cpu limit in percent, above 0 and at most 100, that overrides `starpulse.toml`; null clears it.
   */
  cpuLimit?: number | null;
  display?: DisplayPatch | null;
  enabled?: boolean | null;
  harness?: string | null;
  /**
   * The memory limit in percent, above 0 and at most 100, that overrides `starpulse.toml`; null clears it.
   */
  memoryLimit?: number | null;
  quietHours?: QuietHours | null;
  /**
   * The selected harness's session cap, a whole number above zero that overrides `starpulse.toml`; null clears it.
   */
  sessionCap?: number | null;
  theme?: Theme | null;
}
/**
 * The display choices a write changes; a field left out keeps its value.
 */
export interface DisplayPatch {
  clock?: ("24" | "12") | null;
  density?: ("comfortable" | "compact") | null;
  motion?: boolean | null;
  scale?: number | null;
  view?: ("constellation" | "kanban") | null;
}
/**
 * `GET /api/retired[?task=<id>][&milestone=<id>][&fields=dependencies][&limit=<n>][&before=<cursor>]`: the one
 * retired task `task` names, those of `milestone`, or else a page of them, newest retired first, with `next` the
 * `before` of the page that follows (null on the last); with `fields=dependencies` each is `{task, dependencies}`
 * alone.
 */
export interface RetiredTasks {
  /**
   * The `before` cursor of the next page; null on the last page.
   */
  next?: string | null;
  tasks: RetiredTask[] | RetiredDependencies[];
  [k: string]: unknown;
}
/**
 * A retired task as the board's history store keeps it: its id, its file name and the file's text, byte-for-byte.
 */
export interface RetiredTask {
  name: string;
  task: string;
  text: string;
  [k: string]: unknown;
}
/**
 * A retired task's id and the task ids its file lists as dependencies, with no name or text.
 */
export interface RetiredDependencies {
  dependencies: string[];
  task: string;
  [k: string]: unknown;
}
/**
 * `GET /api/search?q=&limit=&label=&finished_within_days=&before=`: the tasks holding every word of `q`, best
 * match first, each carrying every `label`, with `finished_within_days` open or finished within that many days, and
 * with `before` (a task key) of its prefix and created before it. `GET /api/search/similar` takes the same query and
 * answers the same body, waiting to embed a query it holds no vector for.
 */
export interface SearchResults {
  hits: SearchHit[];
  query: string;
  [k: string]: unknown;
}
/**
 * One task a search found: where it is now, and the text around the match.
 */
export interface SearchHit {
  field?: string;
  lane: string;
  score: number;
  snippet: string;
  task: string;
  title: string;
  [k: string]: unknown;
}
export interface Snapshot {
  /**
   * How many tasks were archived since local midnight, the window of the Done count.
   */
  archived_today?: number | null;
  /**
   * The ids of the done tasks from before local midnight that the board feed holds as a stub, left out of `flows`: the stored body never carries them (the page reads them from `/api/done` and `/api/task/<id>`), a feed's own snapshot does.
   */
  cold_done?: string[] | null;
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
   * Each task an accepted take-over made interactive, by task id; a task never taken over is absent.
   */
  interactive?: {
    [k: string]: boolean;
  } | null;
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
  /**
   * Which State plays which part on the board.
   */
  roles?: Roles | null;
  settled: {
    [k: string]: Settled;
  };
  [k: string]: unknown;
}
export interface FlowSnapshot {
  agents: RawTask[];
  chain?: string[] | null;
  depth?: number | null;
  last?: number | null;
  machine: Machine;
  name: string;
  /**
   * The state and event names the flow's agents' trail points index, each once.
   */
  names?: string[] | null;
  nested?: string[] | null;
  parent?: string | null;
  stuck?: Stuck | null;
  ties?: Tie[] | null;
  [k: string]: unknown;
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
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * Where a lifecycle machine is entered from.
 *
 * `declared` is a Submachine on `machine`'s `state`; `dag` is a launch by `dag`, which names no machine or state.
 */
export interface Tie {
  dag: string | null;
  kind: "declared" | "dag";
  machine: string | null;
  state: string | null;
  /**
   * What has to hold for a declared tie to run; empty otherwise.
   */
  when: string;
  [k: string]: unknown;
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
  [k: string]: unknown;
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
  [k: string]: unknown;
}
export interface LedgerResolved {
  at: string;
  runId: string;
  [k: string]: unknown;
}
export interface LedgerPull {
  number: number;
  repo: string;
  url: string;
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * The 24-hour strip of the merge ledger: per bucket, the merges, the failed ones and the forced reruns.
 */
export interface MergeStrip {
  bucket: number;
  buckets: StripBucket[];
  since: number;
  [k: string]: unknown;
}
export interface StripBucket {
  failed: number;
  merges: number;
  reruns: number;
  [k: string]: unknown;
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
   * The open PR is still a draft.
   */
  draft?: boolean;
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
   * The open PR waits in its base branch's merge queue.
   */
  queued?: boolean;
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
  [k: string]: unknown;
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
  [k: string]: unknown;
}
/**
 * The analytics spend route's body: each task's tokens by phase, oldest task first.
 */
export interface Spend {
  now: number;
  spend: SpendPhase[];
  window_s: number;
  [k: string]: unknown;
}
/**
 * One phase of one task: the tokens its steps burned, and the task's total against its cell's norm.
 */
export interface SpendPhase {
  /**
   * `task_wte` is over three times `norm_wte`.
   */
  above_norm: boolean;
  cache_read: number;
  cache_write: number;
  /**
   * The compactions that fell in the phase.
   */
  compactions: number;
  first_at: number;
  input: number;
  /**
   * The task's `kind-*` label, without the prefix; null when it has none.
   */
  kind: string | null;
  last_at: number;
  models: string[];
  /**
   * Why `phase_norm_wte` is null: `batch umbrella`, `no kind or size`, or `under 5 peers in kind × size`; null when there is a norm.
   */
  no_norm_reason: string | null;
  /**
   * The `profile` of the cell `phase_norm_wte` came from, or `mixed` for the kind and size cell pooling every profile; null when there is no norm.
   */
  norm_profile: string | null;
  /**
   * The sum of `phase_norm_wte` over the task's phases; null when any is null.
   */
  norm_wte: number | null;
  output: number;
  /**
   * The most input, cache-read and cache-write tokens one request held.
   */
  peak_context: number;
  /**
   * `claim`, `implement`, `qa`, `deliver` or `review_fix`; see `docs/sources.md`.
   */
  phase: string;
  /**
   * `wte` is over three times `phase_norm_wte`.
   */
  phase_above_norm: boolean;
  /**
   * The median `wte` of this phase over the tasks of the task's kind, size and `profile` that ran it, or of its kind and size when that profile has under five; null under five.
   */
  phase_norm_wte: number | null;
  /**
   * `<model>-<effort>` of the phase's first main-thread step, each `unknown` when unrecorded.
   */
  profile?: string;
  /**
   * The subagents' share of `steps`.
   */
  side_steps: number;
  /**
   * The task's `size-*` label; null when it has none.
   */
  size: number | null;
  /**
   * Model requests, a subagent's included.
   */
  steps: number;
  task: string;
  /**
   * `wte` summed over the task's phases.
   */
  task_wte: number;
  /**
   * Uncached input + 1.25 x cache write + 0.1 x cache read + 5 x output.
   */
  wte: number;
  [k: string]: unknown;
}
/**
 * `GET /api/task/<id>`: the full record of a task from the board's reader, keyed by its editable fields.
 */
export interface TaskRecord {
  /**
   * The task was archived: read from the archive, off the board's lanes.
   */
  archived?: boolean;
  /**
   * The id of the board's Done lane, which a task's status is read against.
   */
  done?: string | null;
  /**
   * When an archived task last changed in the read model: a Done task's entry into Done.
   */
  entered?: number | null;
  /**
   * The task's stored UUID, which never changes with its key; empty for a task with none yet.
   */
  id?: string;
  /**
   * The task's key, such as `TASK-45`: the same as `task`.
   */
  key?: string;
  record: {
    [k: string]: unknown;
  };
  task: string;
  [k: string]: unknown;
}
/**
 * `GET /api/task-records?ids=A,B`: the `TaskRecord` of each named task the board can read, in the order named.
 */
export interface TaskRecords {
  records: TaskRecord[];
  [k: string]: unknown;
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
  [k: string]: unknown;
}
export interface Bottleneck {
  path_days: number;
  state: string;
  [k: string]: unknown;
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
  [k: string]: unknown;
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
  [k: string]: unknown;
}
export interface ChainState {
  expected_days: number;
  p_goal: number;
  [k: string]: unknown;
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
  [k: string]: unknown;
}
export interface GateSummary {
  bypassable: boolean;
  bypassed: number;
  crossed: number;
  gate: string;
  mandatory: number;
  runs: number;
  witness: GateWitness | null;
  [k: string]: unknown;
}
export interface GateWitness {
  path: string[];
  task: string;
  [k: string]: unknown;
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
  [k: string]: unknown;
}
export interface Norm {
  count: number;
  path: string[];
  [k: string]: unknown;
}
export interface Outlier {
  distance: number;
  path: string[];
  source: string;
  task: string;
  [k: string]: unknown;
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
  [k: string]: unknown;
}
export interface RunGate {
  crossed: boolean;
  dominators: string[];
  gate: string;
  mandatory: boolean;
  post_dominators: string[];
  witness: string[] | null;
  [k: string]: unknown;
}
/**
 * One back-edge a run took: its trips and the days they took, from the target's previous visit to each return.
 */
export interface RunLoop {
  days: number;
  from: string;
  to: string;
  trips: number;
  [k: string]: unknown;
}
export interface Variant {
  count: number;
  path: string[];
  share: number;
  [k: string]: unknown;
}
/**
 * `GET /api/views/<id>`: the one GraphQL document a view stores in `starpulse.toml`.
 */
export interface ViewShown {
  name: string;
  query: string;
  [k: string]: unknown;
}
/**
 * `/api/history-window`: the effective window, the declared default, and whether Admin's override is in effect.
 */
export interface WindowState {
  default: number;
  hours: number;
  overridden: boolean;
  [k: string]: unknown;
}
