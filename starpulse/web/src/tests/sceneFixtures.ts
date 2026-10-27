import { merge, Moves } from "../render/sky";
import { LIFECYCLE_ROLES } from "./lifecycleRoles";
import type { Dag, Machine, Snapshot } from "../api";

/** Test fixtures shared by the scene's test files. */
export const dag = (name: string, steps: [string, string[]][] = []): Dag => ({
  name, status: "succeeded", runId: "r", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null,
  steps: steps.map(([n, depends]) => ({ name: n, depends, status: "succeeded", kind: null, precondition: null, lock: null, last: [] })),
});
export const machine = (ids: string[], extra: Partial<Machine> = {}): Machine => ({
  states: ids.map((id, i) => ({ id, name: id, initial: i === 0, final: false })),
  transitions: [],
  ...extra,
});
// The saved design snapshot's Board (the design mockup): ten states and their transitions, in declaration order.
export const SAVED_STATES = ["new", "ready", "blocked", "waiting", "in_progress", "review", "needs_attention", "done", "completed", "archived"];
export const SAVED_TRANSITIONS = `new>ready new>blocked new>waiting new>in_progress ready>in_progress ready>blocked ready>waiting ready>archived
  blocked>blocked blocked>ready blocked>in_progress blocked>archived waiting>ready waiting>in_progress waiting>archived in_progress>blocked
  in_progress>in_progress in_progress>review in_progress>done in_progress>needs_attention in_progress>archived review>done review>in_progress
  review>archived needs_attention>ready needs_attention>in_progress needs_attention>archived done>completed`.split(/\s+/).map((t) => t.split(">"));
export const savedBoardSky = (W: number, H: number, patch: (snap: Snapshot) => void = () => {}) => {
  const snap: Snapshot = {
    graphs: ["board"],
    flows: [{ name: "board", agents: [], machine: {
      states: SAVED_STATES.map((id, i) => ({ id, name: id, initial: i === 0, final: id === "completed" || id === "archived" })),
      transitions: SAVED_TRANSITIONS.map(([source, target]) => ({ source, target, event: `${source}_${target}` })),
      mainLine: ["new", "ready", "in_progress", "review", "done"],
    } }],
    dags: [], domains: [], settled: {}, error: null, now: 1000, roles: LIFECYCLE_ROLES,
  };
  patch(snap);
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W, H, T: 1000 };
};
