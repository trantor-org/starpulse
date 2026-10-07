// The wire types are generated (types.gen.ts); this file only names what the page derives from them.
import type { ClaimDelta, DagBody, DagsDelta, LedgersDelta, MoveDelta, PullsDelta, RawAgent as WireAgent, Step, SunsDelta, TaskDelta } from "./types.gen";

export * from "./types.gen";

/** The closed set of statuses a run or a step reports. */
export type RunStatus = Step["status"];
export type DagStep = Step;
export type Dag = DagBody;

/** A task as the page holds it: the wire's, plus `today`, set only on a dot the page draws for a day's arrival. */
export type RawAgent = WireAgent & { today?: boolean };

/** One change the server pushes after the snapshot: the event's body, tagged with the event's name. */
export type Delta =
  | ({ kind: "task" } & TaskDelta)
  | ({ kind: "move" } & MoveDelta)
  | ({ kind: "dags" } & DagsDelta)
  | ({ kind: "pulls" } & PullsDelta)
  | ({ kind: "claim" } & ClaimDelta)
  | ({ kind: "suns" } & SunsDelta)
  | ({ kind: "ledgers" } & LedgersDelta);
