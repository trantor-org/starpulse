// What the DAGs view knows about a DAG, apart from how it draws it: its phase, domain and Board ties, the order and filters of
// the catalog, and where a step sits in its constellation. The page's snapshot reaches it as one DagData, read from the Sky.
import { BOARD_COLOR } from "../../render/scene";
import type { Sky } from "../../render/sky";
import type { Cpu, Cue, Dag, DagStep, Domain, Machine, Pool, Rerun } from "../../api";

/** Everything the DAGs view reads from the snapshot: the DAGs, their domains, the pools, the cues, each machine and the server's clock. */
export interface DagData {
  dags: Dag[];
  domains: Domain[];
  pools: Pool[];
  /** The share of all the host's cores each runs instance's runner used, by instance. */
  cpu: Record<string, Cpu>;
  cues: Cue[];
  flows: { name: string; machine: Machine }[];
  now: number;
  /** What each DAG, by name, says about its schedule and its past week. */
  facts: Record<string, DagFacts>;
}

/** A DAG's schedule (its cron expressions, or `manual`), its seven-day statistics (one the server left out stays null, never zero) and the rerun safety it declares (null when it declares none). */
export interface DagFacts { schedule: string; runs: number | null; hours: number | null; medianSeconds: number | null; p95Seconds: number | null; failureShare: number | null; rerun: Rerun | null }

export const dagFacts = (d: Dag): DagFacts => ({
  schedule: d.schedule.join(", ") || "manual",
  runs: d.stats?.runs ?? null,
  hours: d.stats?.hours ?? null,
  medianSeconds: d.stats?.medianSeconds ?? null,
  p95Seconds: d.stats?.p95Seconds ?? null,
  failureShare: d.stats?.failureShare ?? null,
  rerun: d.rerun,
});

/** The snapshot's DAG data as the HUD holds it; a machine's tasks stay behind, so a task move does not redraw the view. */
export const dagData = (sky: Sky): DagData => ({
  dags: sky.dags,
  domains: sky.groups.map((g) => {
    const member = (name: string) => ({ name, runSafe: sky.runnable.has(name) });
    return { name: g.name, dags: g.dags.map(member), ...(g.processes && { processes: g.processes.map((p) => ({ name: p.name, dags: p.dags.map(member) })) }) };
  }),
  pools: sky.pools,
  cpu: sky.cpu,
  cues: sky.cues,
  flows: Object.values(sky.flows).map((f) => ({ name: f.name, machine: f.machine })),
  now: sky.now,
  facts: Object.fromEntries(sky.dags.map((d) => [d.name, dagFacts(d)])),
});

export type Phase = "running" | "queued" | "failed" | "idle" | "ok";
export const short = (n: string) => n.replace(/^[^/]+\//, "");

/** The DAGs that spent run-hours in the last seven days, most first; one with none read or none spent leaves the list. */
export const runHours = (facts: Record<string, DagFacts>) =>
  Object.entries(facts)
    .flatMap(([name, f]) => (f.hours ? [{ name, hours: f.hours }] : []))
    .sort((a, b) => b.hours - a.hours || a.name.localeCompare(b.name));

/** The Runner CPU as one percentage of all the host's cores: every instance's runner share summed. Null when the server served none, which is not zero. */
export const cpuPercent = (cpu: Record<string, Cpu>) => {
  const shares = Object.values(cpu).map((c) => c.share);
  return shares.length ? Math.min(100, 100 * shares.reduce((a, b) => a + b, 0)) : null;
};
export const group = (p: Phase): Exclude<Phase, "queued"> => (p === "queued" ? "running" : p);

export interface Row {
  d: Dag;
  domain: string;
  runSafe: boolean;
  /** The process package of its domain it belongs to; `Other` when the domain packages processes but omits it, null when the domain has none. */
  process: string | null;
  /** Snapshot membership rank: domain order, then process package order, then list order; Other-domain DAGs sort after by name. */
  ord: number;
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
  const home: Record<string, { domain: string; runSafe: boolean; process: string | null; ord: number }> = {};
  let ord = 0;
  for (const dom of data.domains) {
    if (dom.processes?.length) {
      for (const p of dom.processes) {
        for (const x of p.dags) home[x.name] = { domain: dom.name, runSafe: x.runSafe, process: p.name, ord: ord++ };
      }
      for (const x of dom.dags) {
        if (!(x.name in home)) home[x.name] = { domain: dom.name, runSafe: x.runSafe, process: "Other", ord: ord++ };
      }
    } else {
      for (const x of dom.dags) home[x.name] = { domain: dom.name, runSafe: x.runSafe, process: null, ord: ord++ };
    }
  }
  return data.dags.map((d) => {
    const spot = home[d.name], domain = spot?.domain ?? "Other", runSafe = spot?.runSafe ?? false, process = spot?.process ?? null;
    const rank = spot?.ord ?? 1e9;
    const had = made.get(d);
    if (had && had.domain === domain && had.runSafe === runSafe && had.process === process && had.ord === rank) return had;
    const run = d.active?.[0];
    const phase: Phase = run || d.status === "running" ? "running" : d.status === "queued" ? "queued"
      : d.status === "failed" || d.status === "aborted" ? "failed" : d.status === "not_started" ? "idle" : "ok";
    const row: Row = {
      d, domain, runSafe, process, ord: rank, phase,
      steps: Object.fromEntries(d.steps.map((x) => [x.name, run?.steps[x.name] ?? x.status])),
      startedAt: iso(run?.startedAt ?? d.startedAt), finishedAt: iso(d.finishedAt), step: run?.step ?? "",
    };
    made.set(d, row);
    return row;
  });
}

/** Stable catalog order: snapshot membership, then name (phase never moves a row). */
export const order = (a: Row, b: Row) => a.ord - b.ord || a.d.name.localeCompare(b.d.name);

/** The rows a search and a Domain choice leave; the search reads a DAG's name, its steps, its domain and its process. */
export function filterRows(all: Row[], f: { q?: string; dom?: string | null }): Row[] {
  const needle = (f.q ?? "").trim().toLowerCase();
  return all.filter((r) => (!f.dom || r.domain === f.dom) &&
    (!needle || r.d.name.toLowerCase().includes(needle) || r.domain.toLowerCase().includes(needle) || (r.process ?? "").toLowerCase().includes(needle) || r.d.steps.some((x) => x.name.toLowerCase().includes(needle))));
}

/** How many finished DAGs the Just finished bucket at the top of Idle holds. */
export const FRESH = 5;

/** A DAG is Processing while a run of it is running or queued, and Idle otherwise; each snapshot decides, so a run whose end event never came leaves Processing with the next snapshot that no longer has it active. */
export const processing = (r: Row) => group(r.phase) === "running";

export interface Panes {
  /** The DAGs with a run in flight, the one that began first on top and a queued DAG last, so a DAG that starts joins at the bottom. */
  processing: Row[];
  /** Just finished (the latest `FRESH` DAGs to finish, newest first), then every other DAG in catalog order. */
  idle: Row[];
  /** The names in Just finished. */
  fresh: Set<string>;
}

/** Splits the catalog into its two disjoint activity panes. */
export function panes(all: Row[]): Panes {
  const active = all.filter(processing).sort((a, b) => Number(a.phase === "queued") - Number(b.phase === "queued") || a.startedAt - b.startedAt || order(a, b));
  const rest = all.filter((r) => !processing(r)).sort(order);
  const done = rest.filter((r) => r.finishedAt > 0).sort((a, b) => b.finishedAt - a.finishedAt || order(a, b)).slice(0, FRESH);
  const fresh = new Set(done.map((r) => r.d.name));
  return { processing: active, idle: [...done, ...rest.filter((r) => !fresh.has(r.d.name))], fresh };
}

/** The caption each row of a pane opens a group with, null for the rows that continue one: Just finished over the bucket, then a domain wherever the domain changes. */
export function captions(rs: Row[], fresh: Set<string>): (string | null)[] {
  let last = "";
  return rs.map((r) => {
    const label = fresh.has(r.d.name) ? `Just finished · latest ${FRESH}` : r.domain;
    const open = label !== last;
    last = label;
    return open ? label : null;
  });
}

/** Where a row sits on the stage: its column, the slots of header above it (`hs`), its slot down the column and the caption bands above that slot (`k`). `band` is whether its slot opens with a caption band, which the other pane's row of the slot may be the one to need. */
export interface Place { col: 0 | 1; hs: number; slot: number; k: number; band: boolean }

/** Every row's place by DAG name, and each pane's header as `processing-head` and `idle-head`, and the empty Processing pane's hint as `processing-hint`. Beside each other, the Processing row and the Idle row of one index share a slot, so they share a top; a slot spends a caption band only when a row of either pane opens a group there, so rows of one group sit one pitch apart. At a phone's width Idle stacks under Processing, which keeps a slot for its hint when empty. `bands` is the stage's count of caption bands. */
export function places(p: Panes, phone: boolean): { at: Map<string, Place>; bands: number } {
  const open = (rs: Row[]) => captions(rs, p.fresh).map((c) => c !== null);
  const below = phone ? Math.max(p.processing.length, 1) : 0;
  const slots = phone ? below + p.idle.length : Math.max(p.processing.length, p.idle.length, 1);
  const band: boolean[] = Array.from({ length: slots }, () => false);
  open(p.processing).forEach((o, i) => { band[i] = band[i] || o; });
  open(p.idle).forEach((o, i) => { band[below + i] = band[below + i] || o; });
  const above = (slot: number) => band.slice(0, slot).filter(Boolean).length;
  const place = (col: 0 | 1, hs: number, slot: number): Place => ({ col, hs, slot, k: above(slot), band: band[slot] ?? false });
  const at = new Map<string, Place>();
  p.processing.forEach((r, slot) => at.set(r.d.name, place(0, 1, slot)));
  p.idle.forEach((r, slot) => at.set(r.d.name, place(phone ? 0 : 1, phone ? 2 : 1, below + slot)));
  at.set("processing-head", { col: 0, hs: 0, slot: 0, k: 0, band: false });
  at.set("idle-head", phone ? { col: 0, hs: 1, slot: below, k: above(below), band: false } : { col: 1, hs: 0, slot: 0, k: 0, band: false });
  at.set("processing-hint", { col: 0, hs: 1, slot: 0, k: Number(band[0]), band: false });
  return { at, bands: above(slots) };
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
    if (l) out.push({ kind: "launches", text: l.skill, note: l.machine ? `launches ${l.skill}, which runs the ${l.machine} machine` : `launches ${l.skill}`, color: "var(--agent)" });
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

/** What a DAG declares about a rerun, as the modal header says it; null for a DAG that declares nothing, so the view makes no claim for it. */
export const rerunLine = (x: Rerun | null) => (!x ? null : x.key ? `once per ${x.key}` : x.repeats ? `repeats on rerun · ${x.repeats}` : "safe to rerun");

/** What a step's line adds to its history: the precondition that may skip it, the lock it takes, and the repeat the DAG declares at it. */
export const stepNote = (s: DagStep, x: Rerun | null) =>
  [s.precondition && `when ${s.precondition}`, s.lock && `lock ${s.lock}`, x?.repeats && x.step === s.name && `repeats · ${x.repeats}`].filter(Boolean).join(" · ");

/** Why Run now is refused for a DAG, or null when it may start. Only a run-safe DAG has the button; the modal shows it disabled with this reason. */
export const refusal = (r: Row, starting = false): string | null =>
  r.phase === "running" ? "Already running" : r.phase === "queued" ? "Already queued" : !r.runSafe ? "Not run-safe: this DAG changes live state, so StarPulse will not start it. Run it from its workflow runner."
    : starting ? "Starting…" : null;
