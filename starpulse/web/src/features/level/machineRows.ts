// The machine ledger's rows: every machine entered from the machine at the top is one row under it. Pure: which machines are rows, in what
// order, and what each row's meta column says. The renderer draws them; scene.ts places them under the top (machineLedger.ts).
import type { FlowSnapshot } from "../../api";

/**
 * The machines entered from `top`, newest activity first. One sequence, nothing pinned: a machine with a task stuck keeps the place its last
 * activity gives it (`last` already covers every machine nested below it). `held` is the order the page is holding still: it keeps that order for
 * the machines still there and lists any new one after them.
 */
export function rankRows(flows: Record<string, FlowSnapshot>, top: string, held?: readonly string[]): string[] {
  const rows = Object.values(flows).filter((f) => f.parent === top && f.name !== top).sort((a, b) => (b.last ?? 0) - (a.last ?? 0) || (a.name < b.name ? -1 : 1)).map((f) => f.name);
  if (!held) return rows;
  const kept = held.filter((m) => rows.includes(m));
  return [...kept, ...rows.filter((m) => !kept.includes(m))];
}

export interface RowMeta {
  /** The name line's end: a chevron; the band under the row shows the machines entered from it (machineChain.ts). */
  end: string;
  /** Where the machine is entered from: the line's text, the state it is entered from (the dot's colour), and how the page learned of it. */
  tie: { text: string; machine: string | null; state: string | null; kind: "declared" | "observed" | "dag" | "none" };
  /** What its tasks are doing, whether a task here or nested below is stuck, and whether the machine has been quiet over an hour. */
  status: { text: string; stuck: boolean; idle: boolean };
  /** The states and tasks it holds. */
  sub: string;
}

/** How long a span of seconds has run: hours and minutes from an hour, else minutes. */
export function age(s: number): string {
  return s >= 3600 ? `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}` : `${Math.max(1, Math.round(s / 60))}m`;
}
const hhmm = (sec: number) => new Date(sec * 1000).toLocaleTimeString("en-US", { timeZone: "America/Phoenix", hour: "2-digit", minute: "2-digit", hour12: false });
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
/** A machine whose last task moved over an hour ago is idle. */
const IDLE = 3600;

/** The rows with a task stuck here or in a machine nested below them: the header counts them. */
export function stuckCount(flows: Record<string, FlowSnapshot>, rows: readonly string[]): number {
  return rows.filter((r) => flows[r]?.stuck).length;
}

function statusOf(flows: Record<string, FlowSnapshot>, name: string, now: number): RowMeta["status"] {
  const f = flows[name], n = f.agents.length, below = (f.nested ?? []).reduce((a, m) => a + (flows[m]?.agents.length ?? 0), 0);
  const last = f.last ?? 0, idle = f.last == null || now - last > IDLE;
  if (f.stuck) {
    const at = age(now - f.stuck.since);
    return { text: f.stuck.machine === name ? `stuck ${at} in ${stateName(flows, name, f.stuck.state)}` : `nested stuck ${at} in ${f.stuck.machine}`, stuck: true, idle };
  }
  const when = f.last == null ? "no activity" : idle ? `idle ${age(now - last)}` : `last ${hhmm(last)}`;
  if (n) return { text: `${plural(n, "task")} · ${when}`, stuck: false, idle };
  return { text: below ? `${below} ${below === 1 ? "task" : "tasks"} nested · ${when}` : "no sessions this hour", stuck: false, idle };
}

const stateName = (flows: Record<string, FlowSnapshot>, machine: string, state: string) => flows[machine]?.machine.states.find((s) => s.id === state)?.name ?? state;

/** What a row's meta column says about `name`, a machine entered from `top`. */
export function rowMeta(flows: Record<string, FlowSnapshot>, name: string, top: string, now: number): RowMeta {
  const f = flows[name], lead = f.ties?.[0], dags = (f.ties ?? []).filter((t) => t.kind === "dag").map((t) => t.dag);
  const n = f.agents.length;
  let tie: RowMeta["tie"] = { text: "no tie this hour", machine: null, state: null, kind: "none" };
  if (lead && lead.kind !== "dag" && lead.machine && lead.state) {
    const from = lead.machine === top ? `from ${stateName(flows, lead.machine, lead.state)}` : `on ${lead.machine} › ${stateName(flows, lead.machine, lead.state)}`;
    tie = { text: `${from} · ${lead.kind === "declared" ? "declared" : `×${lead.count}`}`, machine: lead.machine, state: lead.state, kind: lead.kind };
  } else if (dags.length) tie = { text: `✦ ${dags.join(", ")}`, machine: null, state: null, kind: "dag" };
  return {
    end: "›",
    tie,
    status: statusOf(flows, name, now),
    sub: `${f.machine.states.length} states · ${n} task${n === 1 ? "" : "s"}`,
  };
}

/** What an empty lane says: the machine on top has none entered from it, and Escape is the way back. */
export const emptyNote = (machine: string): string => `nothing is entered from ${machine} · Esc steps back out`;

/** The first row, in the order `rows` run, with a tie to `state` of `top`: where a click on that state of the top scrolls to. */
export function firstOpened(flows: Record<string, FlowSnapshot>, rows: readonly string[], top: string, state: string): string | null {
  return rows.find((r) => flows[r]?.ties?.some((t) => t.kind !== "dag" && t.machine === top && t.state === state)) ?? null;
}
