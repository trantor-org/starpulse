// A task's path across the machine ledger: every session it has in the template and in the machines entered from it, in time order. Pure; the
// renderer draws it over the ledger (drawTop, drawLane).
import type { FlowSnapshot, RawAgent } from "../../api";

export interface Session {
  machine: string;
  agent: RawAgent;
}
/** A state of one machine. */
export interface Spot {
  machine: string;
  state: string;
}
/** One step of the path: a session entering a machine from the state it left, or a hop between two states of one machine. */
export interface Step {
  kind: "entry" | "hop";
  a: Spot;
  b: Spot;
  /** A hop its machine has no line for. */
  off: boolean;
  at: number;
  /** Its place in the path, from 1. */
  n: number;
}

/** When a session started: its first move, else its last activity. */
export const start = (a: RawAgent) => a.trail?.[0]?.at ?? a.active ?? 0;
function stateAt(a: RawAgent, t: number): string | null {
  let s: string | null = null;
  for (const x of a.trail ?? []) if (x.at <= t) s = x.state;
  return s;
}
const initOf = (f: FlowSnapshot) => (f.machine.states.find((s) => s.initial) ?? f.machine.states[0])?.id;

/** Every session of the task `agent` (in `machine`) belongs to, across the machines; a session with no task is only itself. */
export function sessionsOf(flows: Record<string, FlowSnapshot>, machine: string, agent: RawAgent): Session[] {
  if (!agent.task) return [{ machine, agent }];
  return Object.values(flows).flatMap((f) => f.agents.filter((a) => a.task === agent.task).map((a) => ({ machine: f.name, agent: a })));
}

/** The machines a pinned task holds: those it had a session in when pinned, which the open card lists, and any it has entered since. */
export function heldBy(flows: Record<string, FlowSnapshot>, task: string | null, pinned: readonly string[]): string[] {
  const now = task ? Object.values(flows).filter((f) => f.agents.some((a) => a.task === task)).map((f) => f.name) : [];
  return [...new Set([...pinned, ...now])];
}

/** The state a session was entered from: the newest of the task's other sessions still open then, outside the template, else its template session. */
function parentOf(sessions: Session[], s: Session, template: string): Spot | null {
  const t0 = start(s.agent), sib = sessions.filter((b) => b !== s && b.machine !== s.machine);
  const open = sib.filter((b) => b.machine !== template && start(b.agent) <= t0 && (b.agent.active ?? 0) >= t0 - 600).sort((x, y) => start(y.agent) - start(x.agent));
  const p = open[0] ?? sib.find((b) => b.machine === template);
  return p ? { machine: p.machine, state: stateAt(p.agent, t0) ?? p.agent.trail?.[0]?.state ?? p.agent.state } : null;
}

/**
 * The path, numbered in time order: each session's entry into its machine (outside the template) and each hop along its trail. `has` says whether
 * the ledger draws a state; a step to or from one it does not is left out before numbering.
 */
export function traceSteps(flows: Record<string, FlowSnapshot>, sessions: Session[], template: string, has: (s: Spot) => boolean): Step[] {
  const steps: Omit<Step, "n">[] = [];
  for (const s of [...sessions].sort((x, y) => start(x.agent) - start(y.agent))) {
    const f = flows[s.machine], init = f && initOf(f);
    if (!f || !init) continue;
    if (s.machine !== template && s.agent.task) {
      const a = parentOf(sessions, s, template), b = { machine: s.machine, state: init };
      if (a && has(a) && has(b)) steps.push({ kind: "entry", a, b, off: false, at: start(s.agent) - 0.5 });
    }
    let from = init;
    for (const st of s.agent.trail ?? []) {
      const a = { machine: s.machine, state: from }, b = { machine: s.machine, state: st.state };
      if (st.state !== from && has(a) && has(b)) steps.push({ kind: "hop", a, b, off: !f.machine.transitions.some((t) => t.source === from && t.target === st.state), at: st.at });
      from = st.state;
    }
  }
  return steps.sort((x, y) => x.at - y.at).map((s, i) => ({ ...s, n: i + 1 }));
}
