// What the DAGs view knows about a DAG, apart from how it draws it: its phase, domain and Board ties, the order and filters of
// the catalog, and where a step sits in its constellation. The page's snapshot reaches it as one DagData, read from the Sky.
import { BOARD_COLOR } from "../../render/scene";
import type { Sky } from "../../render/sky";
import type { Cue, Dag, DagStep, Domain, Machine, Pool } from "../../api";

/** Everything the DAGs view reads from the snapshot: the DAGs, their domains, the pools, the cues, each machine and the server's clock. */
export interface DagData {
  dags: Dag[];
  domains: Domain[];
  pools: Pool[];
  cues: Cue[];
  flows: { name: string; machine: Machine }[];
  now: number;
}

/** The snapshot's DAG data as the HUD holds it; a machine's tasks stay behind, so a task move does not redraw the view. */
export const dagData = (sky: Sky): DagData => ({
  dags: sky.dags,
  domains: sky.groups.map((g) => ({ name: g.name, dags: g.dags.map((name) => ({ name, runSafe: sky.runnable.has(name) })) })),
  pools: sky.pools,
  cues: sky.cues,
  flows: Object.values(sky.flows).map((f) => ({ name: f.name, machine: f.machine })),
  now: sky.now,
});

export type Phase = "running" | "queued" | "failed" | "idle" | "ok";
/** The Status menu's choices; a queued DAG counts as running. */
export const PHASES: [Exclude<Phase, "queued">, string][] = [["running", "Running"], ["failed", "Failing"], ["idle", "Not run"], ["ok", "Healthy"]];
export const short = (n: string) => n.replace(/^[^/]+\//, "");
export const group = (p: Phase): Exclude<Phase, "queued"> => (p === "queued" ? "running" : p);

export interface Row {
  d: Dag;
  domain: string;
  runSafe: boolean;
  phase: Phase;
  /** Each step's status in the run the row shows: the active one, else the last. */
  steps: Record<string, string>;
  /** Epoch seconds; 0 when the DAG has not run. */
  startedAt: number;
  finishedAt: number;
  /** The step an active run is in. */
  step: string;
}

const iso = (s: string) => (s ? Date.parse(s) / 1000 : 0);

/** The row each DAG object last made, so a DAG a delta left as it was keeps its row's reference and the view redraws only the rows that changed. */
const made = new WeakMap<Dag, Row>();

export function rows(data: DagData): Row[] {
  const home: Record<string, { domain: string; runSafe: boolean }> = {};
  for (const dom of data.domains) for (const x of dom.dags) home[x.name] = { domain: dom.name, runSafe: x.runSafe };
  return data.dags.map((d) => {
    const had = made.get(d), domain = home[d.name]?.domain ?? "Other", runSafe = home[d.name]?.runSafe ?? false;
    if (had && had.domain === domain && had.runSafe === runSafe) return had;
    const run = d.active?.[0];
    const phase: Phase = run || d.status === "running" ? "running" : d.status === "queued" ? "queued"
      : d.status === "failed" || d.status === "aborted" ? "failed" : d.status === "not_started" ? "idle" : "ok";
    const row: Row = {
      d, domain, runSafe, phase,
      steps: Object.fromEntries(d.steps.map((x) => [x.name, run?.steps[x.name] ?? x.status])),
      startedAt: iso(run?.startedAt ?? d.startedAt), finishedAt: iso(d.finishedAt), step: run?.step ?? "",
    };
    made.set(d, row);
    return row;
  });
}

const RANK: Record<Phase, number> = { running: 0, queued: 1, failed: 2, idle: 3, ok: 4 };
export const order = (a: Row, b: Row) => RANK[a.phase] - RANK[b.phase] || b.finishedAt - a.finishedAt || a.d.name.localeCompare(b.d.name);

/** The Last run menu's windows, each with its length in seconds; no choice shows every DAG. */
export const RECENCY: [string, number][] = [["Past hour", 3600], ["Past day", 86400], ["Past week", 7 * 86400], ["Past month", 30 * 86400], ["Past year", 365 * 86400]];

/** Whether a row's DAG is active now or last ran at or after `since` (epoch seconds); a never-run DAG is not recent. */
export const recent = (r: Row, since: number) => group(r.phase) === "running" || (r.phase !== "idle" && Math.max(r.startedAt, r.finishedAt) >= since);

/** The rows a search, a Status choice, a Domain choice and a Last run window (`since`, epoch seconds; 0 for all) leave; the search reads a DAG's name, its steps and its domain. */
export function filterRows(all: Row[], f: { q?: string; only?: Exclude<Phase, "queued"> | null; dom?: string | null; since?: number }): Row[] {
  const needle = (f.q ?? "").trim().toLowerCase();
  return all.filter((r) => (!f.only || group(r.phase) === f.only) && (!f.dom || r.domain === f.dom) && (!f.since || recent(r, f.since)) &&
    (!needle || r.d.name.toLowerCase().includes(needle) || r.domain.toLowerCase().includes(needle) || r.d.steps.some((x) => x.name.toLowerCase().includes(needle))));
}

/** Where a DAG touches the Board: the event that cues it, the transitions it writes, the skill it launches. `ev` is the transition's event, which has a Ledger on the Star Map. */
export interface Tie { kind: "cue" | "writes" | "launches" | "acts"; text: string; note: string; color: string; ev?: string }

export function ties(data: DagData, name: string): Tie[] {
  const out: Tie[] = [];
  const board = data.flows.find((f) => f.name === "board")?.machine;
  const stateName = (m: Machine, id: string) => m.states.find((x) => x.id === id)?.name ?? id;
  for (const c of data.cues) if (c.dag === name) out.push({ kind: "cue", ev: c.event, text: `on ${c.event}`, note: `${c.on}; the task lands in ${board ? stateName(board, c.state) : c.state}`, color: BOARD_COLOR[c.state] ?? "var(--slate)" });
  for (const f of data.flows) {
    const m = f.machine;
    for (const [ev, ws] of Object.entries(m.writers ?? {})) if (ws.some((w) => w.actor === name)) {
      const t = m.transitions.find((x) => x.event === ev);
      out.push({ kind: "writes", ev: t ? ev : undefined, text: t ? stateName(m, t.target) : ev,
        note: t ? `${ev}: ${stateName(m, t.source)} → ${stateName(m, t.target)}${f.name === "board" ? "" : ` (${f.name})`}` : ev, color: (t && BOARD_COLOR[t.target]) ?? "var(--agent)" });
    }
    const l = m.launches?.[name];
    if (l) out.push({ kind: "launches", text: l.skill, note: l.flow ? `launches ${l.skill}, which runs the ${l.flow} machine` : `launches ${l.skill}`, color: "var(--agent)" });
  }
  if (board?.dagActors?.includes(name) && !out.some((t) => t.kind === "writes")) out.push({ kind: "acts", text: "Board", note: "acts on Board tasks", color: "var(--agent)" });
  const seen = new Set<string>();
  out.sort((a, b) => Number(!a.ev) - Number(!b.ev));
  return out.filter((t) => !seen.has(t.kind + t.text + (t.ev ?? "")) && seen.add(t.kind + t.text + (t.ev ?? "")));
}

export function ago(now: number, t: number) {
  const s = Math.max(0, now - t);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
export function took(a: number, b: number) {
  const s = Math.max(0, Math.round(b - a));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** Steps placed by depth (longest path from a root): one column per depth, a wide fan folded into a small cluster of `rows`-high
 *  sub-columns `sub` apart, the columns spread `gap` apart at most so the whole fits `w`. With `px` (a label's width per character)
 *  each gap first makes room for its two columns' names: in full beside a stacked column, and in half between two single steps,
 *  whose names then alternate above and below (`up`). */
export function place(steps: DagStep[], w: number, h: number, pad: number, rows: number, sub: number, gap: number, gy: number, px = 0) {
  const by = Object.fromEntries(steps.map((x) => [x.name, x]));
  const depth: Record<string, number> = {};
  const dep = (n: string, seen = new Set<string>()): number => {
    if (n in depth) return depth[n];
    if (seen.has(n)) return 0;
    seen.add(n);
    return (depth[n] = Math.max(0, ...(by[n]?.depends ?? []).filter((p) => by[p]).map((p) => dep(p, seen) + 1)));
  };
  steps.forEach((x) => dep(x.name));
  const cols: string[][] = [];
  for (const x of steps) (cols[depth[x.name]] ??= []).push(x.name);
  const span = cols.map((c) => (Math.ceil(c.length / rows) - 1) * sub);
  const lw = cols.map((c) => px * Math.max(...c.map((n) => n.length)));
  const lone = (d: number) => cols[d].length === 1;
  const floor = cols.slice(1).map((_, i) => !px ? sub : lone(i) && lone(i + 1) ? Math.max(9.5 * px, (lw[i] + lw[i + 1]) / 4 + 8) : (lw[i] + lw[i + 1]) / 2 + 14);
  const extra = Math.max(0, w - 2 * pad - span.reduce((a, b) => a + b, 0) - floor.reduce((a, b) => a + b, 0)) / Math.max(1, floor.length);
  const gx = floor.map((f) => f + Math.min(extra, Math.max(0, gap - f)));
  const alt = !!px && gx.some((g, i) => lone(i) && lone(i + 1) && g < (lw[i] + lw[i + 1]) / 2 + 8);
  const at: Record<string, { x: number; y: number }> = {};
  let x0 = pad;
  cols.forEach((c, d) => {
    c.forEach((name, i) => (at[name] = { x: x0 + Math.floor(i / rows) * sub, y: h / 2 + ((i % rows) - (Math.min(rows, c.length - Math.floor(i / rows) * rows) - 1) / 2) * gy }));
    x0 += span[d] + (gx[d] ?? 0);
  });
  const up = (name: string) => alt && lone(depth[name]) && depth[name] % 2 === 1;
  return { at, up, cols: cols.length, wide: Math.max(1, ...cols.map((c) => Math.min(rows, c.length))), span: x0 + pad };
}

/** The modal's chart: a name `px` wide a character, a folded fan's sub-columns a longest name apart, at most five steps high. */
export function bigPlace(steps: DagStep[], w: number, h: number, px: number) {
  const lw = px * Math.max(0, ...steps.map((x) => x.name.length));
  return place(steps, w, h, Math.max(44, lw / 2 + 6), 5, Math.max(92, lw + 16), 120, 40, px);
}

/** The modal chart's height: the five-high fan of a folded cluster, or room for one row of steps and their names. */
export const chartHeight = (wide: number) => Math.max(110, 74 + (wide - 1) * 40);

/** Why Run now is refused for a DAG, or null when it may start. Only a run-safe DAG has the button; the modal shows it disabled with this reason. */
export const refusal = (r: Row, starting = false): string | null =>
  r.phase === "running" ? "Already running" : r.phase === "queued" ? "Already queued" : !r.runSafe ? "Not run-safe: this DAG changes live state, so StarPulse will not start it. Run it from its workflow runner."
    : starting ? "Starting…" : null;
