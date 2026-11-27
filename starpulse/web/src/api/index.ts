// The wire types are generated (types.gen.ts); this file only names what the page derives from them.
import type { DagBody, FlowSnapshot as WireFlow, RawTask as WireAgent, Snapshot as WireSnapshot, Step } from "./types.gen";

export * from "./types.gen";

/** The closed set of statuses a run or a step reports. */
export type RunStatus = Step["status"];
export type DagStep = Step;
export type Dag = DagBody;

/** One step of a machine task's trail as the page reads it; `id` names a third-party machine's subject. */
export interface TrailStep {
  state: string;
  event: string;
  at: number;
  id?: string | null;
}

/** `T` with its `K` field typed `V`: `Omit` would turn every field into `unknown`, since the generated types keep an index signature. */
type With<T, K extends string, V> = { [P in keyof T as string extends P ? never : P]: P extends K ? V : T[P] };

/** A task as the page holds it: the wire's with its trail decoded, plus `today`, set only on a dot the page draws for a day's arrival. */
export type RawTask = With<WireAgent, "trail", TrailStep[] | null> & { today?: boolean };
/** A flow as the page holds it: its agents' trails decoded, its `names` the table they were interned in. */
export type FlowSnapshot = With<WireFlow, "agents", RawTask[]>;
export type Snapshot = With<WireSnapshot, "flows", FlowSnapshot[]>;

/** The kind of change a subscription frame folds into the held board: a task, the jobs (`dags`) or the merge ledger. */
export type Delta = { kind: "task" | "dags" | "ledgers" };
