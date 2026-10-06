// The /api/events contract, as starpulse.server writes it.

export interface MachineState {
  id: string;
  name: string;
  initial: boolean;
  final: boolean;
}

export interface Transition {
  source: string;
  target: string;
  event: string;
}

/** Who fires a Board event: a runs workflow (by `<instance>/<workflow>` name), `operator` or `agent`. */
export interface Writer {
  actor: string;
  trigger: string;
}

/** Where a Board state opens into another machine, and which Board event each inner final state fires. */
export interface SubFlow {
  state: string;
  flow: string;
  exits: Record<string, string>;
  /** The flow the link opens under: `board`, or the flow whose `state` it hangs off. */
  parent: string;
  /** What has to hold for the inner flow to run under `state`; empty when always. */
  when: string;
}

/** A runs workflow's launch: the skill it starts and the flow that skill draws, null when it has none. */
export interface Launch {
  skill: string;
  flow: string | null;
}

export interface Machine {
  states: MachineState[];
  transitions: Transition[];
  /** The flows that open under this machine's states; the board's first is its In Progress delivery machine. */
  subflows?: SubFlow[];
  /** Only the board machine: the skill flow each launching DAG starts. */
  launches?: Record<string, Launch>;
  /** Only the board machine: its writers per event. */
  writers?: Record<string, Writer[]>;
  /** Only the board machine: the writers that are runs workflows. */
  dagActors?: string[];
  /** Only the board machine: the state ids along its axis, in order (New to Done). */
  mainLine?: string[];
}

export interface TrailStep {
  state: string;
  event: string;
  at: number;
}

/** A Backlog task. On the board its state is its lane; on every other machine, the state its latest machine event left it in. */
export interface RawAgent {
  id: string;
  title: string;
  state: string;
  model: string;
  labels?: string[];
  /** A task's dependencies, as task ids. */
  dependencies?: string[];
  /** A task's pull requests: the PR URLs among its references. */
  prs?: string[];
  /** A machine's task: the id of the Backlog task its events name. */
  task?: string | null;
  steps?: number;
  trail?: TrailStep[];
  active?: number;
  /** A task's Backlog description. */
  description?: string;
  /** A Board task's milestone; empty or absent when it has none. */
  milestone?: string;
  /** The Board lane the task left on its last move; absent before it has moved. */
  previous?: string;
  /** The verdict on each Board column the task may move to, by state id. */
  moves?: Record<string, { allowed: boolean; reason: string; skill: string }>;
  /** When a Board task entered its lane, epoch seconds; absent when the server holds no time for it. */
  entered?: number;
  /** When a Board task was created, in epoch seconds; null or absent when the board does not say. */
  created?: number | null;
  /** Drawn on a starting or terminal Board state as one of the day's arrivals there, not as the task's own place. */
  today?: boolean;
}

/** A task that left the Board's lanes for good: where it settled, when, and the title and assignee it settled with. */
export interface Settled {
  state: string;
  at: number | null;
  created: number | null;
  title: string;
  model: string;
}

export interface FlowSnapshot {
  name: string;
  machine: Machine;
  agents: RawAgent[];
}

/** The closed set of statuses a run or a step reports; the runs contract's `RunStatus`. */
export type RunStatus = "not_started" | "queued" | "running" | "succeeded" | "failed" | "aborted" | "skipped";

/** One step of a DAG: the steps it waits on, its status in the DAG's latest run and the phase kind it declares. */
export interface DagStep {
  name: string;
  depends: string[];
  status: RunStatus;
  /** The engine's own status when it differs from `status`. */
  raw?: string | null;
  kind?: string | null;
}

/** One running or queued run of a DAG: the step it is in and when it entered it, and every step's status in this run. */
export interface ActiveRun {
  runId: string;
  status: RunStatus;
  /** The engine's own status when it differs from `status`. */
  raw?: string | null;
  startedAt: string;
  /** The step the run is in; empty when it is in none. */
  step: string;
  stepStartedAt: string;
  steps: Record<string, RunStatus>;
}

/** A concurrency pool: how many runs it admits at once, and how many it runs and holds waiting. */
export interface Pool {
  name: string;
  cap: number;
  running: number;
  queued: number;
}

export interface Dag {
  name: string;
  status: RunStatus;
  /** The engine's own status when it differs from `status`. */
  raw?: string | null;
  runId: string;
  startedAt: string;
  finishedAt: string;
  steps: DagStep[];
  /** Every running or queued run of the DAG, including concurrent ones. */
  active?: ActiveRun[];
  /** The name of the `Pool` the DAG runs on; empty when its adapter reports none. */
  pool?: string;
}

/** A domain's DAGs, and whether each is declared safe to run from the page. */
export interface Domain {
  name: string;
  dags: { name: string; runSafe: boolean }[];
}

/** One pull request a task cites, as GitHub last answered the server. */
export interface Pull {
  number: number;
  url: string;
  /** The head commit's check rollup. */
  checks: "pass" | "failing" | "pending" | "none";
  merged: boolean;
  /** Unresolved review threads. */
  threads: number;
  /** True when the last read failed and this is the read before it. */
  stale: boolean;
}

/** A DAG that runs on the same trigger as a Board event's writer but writes no lane itself. */
export interface Cue {
  dag: string;
  event: string;
  state: string;
  on: string;
}

/** One change the server pushes after the snapshot: a Board task that moved (`agent` null once it left the lanes), a task a machine event placed on another machine, or a runs instance's workflows. */
export type Delta =
  | { kind: "task"; id: string; agent: RawAgent | null; settled: Settled | null }
  | { kind: "move"; flow: string; id: string; agent: RawAgent }
  | { kind: "dags"; dags: Dag[]; pools?: Pool[]; error: string | null }
  | { kind: "pulls"; pulls: Record<string, Pull[]> }
  | { kind: "claim"; task: string; reason: string; at: number };

export interface Snapshot {
  /** Every lifecycle machine the server draws, and `runs`. */
  graphs: string[];
  /** The DAG domains. */
  domains?: Domain[];
  /** The DAGs cued by a Board event. */
  cues?: Cue[];
  /** The Backlog board a task links into. */
  boardUrl?: string | null;
  /** A Backlog.md project found beside the config while the default board is shown, and how to switch to it. */
  hint?: string | null;
  dags: Dag[];
  /** The concurrency pools the DAGs run on. */
  pools?: Pool[];
  flows: FlowSnapshot[];
  /** Each open task's pull requests, by task id. */
  pulls?: Record<string, Pull[]>;
  /** Each task's latest In Progress claim the board writer refused an agent, and when (epoch seconds). */
  claims?: Record<string, { reason: string; at: number }>;
  /** What the board writes: the task modal draws Edit and Archive only when its board does. */
  capabilities?: { edit: boolean; archive: boolean };
  settled: Record<string, Settled>;
  error: string | null;
  /** True while a just-started server is still reading its board: its Board is partial until a snapshot without it follows. */
  reading?: boolean;
  now: number;
}
