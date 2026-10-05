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
  /** The verdict on each Board column the task may move to, by state id. */
  moves?: Record<string, { allowed: boolean; reason: string; skill: string }>;
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

export interface Dag {
  name: string;
  status: RunStatus;
  /** The engine's own status when it differs from `status`. */
  raw?: string | null;
  runId: string;
  startedAt: string;
  finishedAt: string;
  steps: DagStep[];
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
  | { kind: "task"; id: string; agent: RawAgent | null; settled: string | null }
  | { kind: "move"; flow: string; id: string; agent: RawAgent }
  | { kind: "dags"; dags: Dag[]; error: string | null }
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
  dags: Dag[];
  flows: FlowSnapshot[];
  /** Each open task's pull requests, by task id. */
  pulls?: Record<string, Pull[]>;
  /** Each task's latest In Progress claim the board writer refused an agent, and when (epoch seconds). */
  claims?: Record<string, { reason: string; at: number }>;
  settled: Record<string, string>;
  error: string | null;
  now: number;
}
