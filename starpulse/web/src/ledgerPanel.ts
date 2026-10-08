// The Ledger's merge panel, tips and doctor banner: the words a merge row, its panel and the contract banner show. Pure: the renderer owns when they
// open and where they sit, and hands over the clock, the colours and the links.
import { dur, markOf, shortApplied, statusLine, type Tie } from "./ledger";
import { esc } from "./panels";
import type { GNode, LedgerView, Scene } from "./scene";
import type { ContractReport, LedgerRow, LedgerRun, RunStatus } from "./types";

export interface PanelCtx {
  event: string;
  /** The names of the Board states the event moves a task between. */
  from: string;
  to: string;
  ties: readonly Tie[];
  /** Each template's step names, by DAG. */
  steps: Record<string, readonly string[]>;
  /** The steps each DAG applies only sometimes, by DAG. */
  optional: Record<string, ReadonlySet<string>>;
  /** Colours by run state, and `waiting`. */
  palette: Record<string, string>;
  /** Epoch seconds the page draws at. */
  now: number;
  hm: (sec: number) => string;
  by: (key: string) => LedgerRow | undefined;
  /** A task's link, as HTML. */
  task: (id: string) => string;
  /** The forced reruns being asked for, and the refusals the server gave; none until the viewer asks for one. */
  rerun?: { busy: ReadonlySet<string>; refused: Readonly<Record<string, string>> };
}

export interface Banner {
  tone: "ok" | "warn" | "fail";
  head: string;
  sub: string;
}

const RULE = { forced: "clears on a forced rerun", next: "clears on the next success" } as const;
const BY = { forced: "a forced rerun", next: "the next success" } as const;
const epoch = (iso: string) => (iso ? Date.parse(iso) / 1000 : 0);
const cross = (row: LedgerRow) => row.appliedBy !== undefined;
const sha7 = (row: LedgerRow) => (row.sha ?? row.key).slice(0, 7);

/** One line per cued run of the merge that failed: its step, and when and by what the failure was resolved, or the rule that will resolve it. */
export function failHtml(row: LedgerRow, ctx: PanelCtx, cls: string): string {
  return ctx.ties.flatMap((tie) => {
    const f = row.fails[tie.dag];
    if (!f) return [];
    const rule = f.resolves ?? tie.resolves ?? "next";
    const state = f.resolved ? `resolved ${ctx.hm(epoch(f.resolved.at))} by ${BY[rule]}` : `unresolved, ${RULE[rule]}`;
    return [`<div class="${cls}" style="color:${ctx.palette[f.resolved ? "succeeded" : "failed"]}">${esc(tie.dag)} ✕ ${esc(f.step)}: ${state}</div>`];
  }).join("");
}

/** A Force rerun button for each DAG whose failure on `row` is unresolved, disabled while its request is out, with the server's refusal under it. */
export function rerunHtml(row: LedgerRow, ctx: PanelCtx): string {
  return ctx.ties.flatMap((tie) => {
    if (!row.fails[tie.dag] || row.fails[tie.dag].resolved) return [];
    const dag = esc(tie.dag), busy = ctx.rerun?.busy.has(tie.dag), refusal = ctx.rerun?.refused[tie.dag];
    const button = busy ? `<button class="run" data-rerun="${dag}" disabled>↻ Rerunning ${dag}…</button>` : `<button class="run" data-rerun="${dag}">↻ Force rerun ${dag}</button>`;
    return [button + (refusal ? `<div class="note" style="color:${ctx.palette.failed}">${esc(refusal)}</div>` : "")];
  }).join("");
}

/** A step's state in a run; a template of one step takes the run's own. */
const stepState = (run: LedgerRun, step: string, steps: readonly string[]): RunStatus => run.steps[step] ?? (steps.length === 1 ? run.status : "not_started");

const pairing = (row: LedgerRow, run: LedgerRun) => {
  if (markOf(run) === "keyed") return `<div class="k">paired by commit: AFTER=${esc(sha7(row))}</div>`;
  const n = run.ambiguous;
  return `<div class="k" style="${n ? "color:#f59e0b" : ""}">≈ paired by time: the newest merge before the run started${n ? `; ${n} more merge${n > 1 ? "s" : ""} landed first, so it may be theirs` : ""}</div>`;
};

function tieRow(row: LedgerRow, tie: Tie, ctx: PanelCtx): string {
  const run = row.runs[tie.dag], name = `<td>${esc(tie.dag)}</td>`;
  if (!run) {
    const line = statusLine(row, tie, undefined, { event: ctx.event, now: ctx.now, hm: ctx.hm, optional: new Set(), by: ctx.by });
    return `<tr>${name}<td class="k">no run: ${esc(line.main)}${line.sub ? ` · ${esc(line.sub)}` : ""}</td></tr>`;
  }
  const names = ctx.steps[tie.dag] ?? [], start = epoch(run.startedAt), end = epoch(run.finishedAt), over = run.status !== "running" && run.status !== "queued" && end > 0;
  const chips = names.map((n) => {
    const s = stepState(run, n, names), c = ctx.palette[s] ?? "#94a3b8";
    return `<span class="chip" style="color:${c};border-color:${c}66" title="${esc(s)}">${esc(n)}</span>`;
  }).join(" ");
  const applied = shortApplied(run, ctx.optional[tie.dag] ?? new Set());
  const state = run.status === "queued" ? "waiting to start" : run.status.replace("_", " ");
  const window = start ? ` · ${ctx.hm(start)}${over ? `–${ctx.hm(end)} · ${dur(end - start)}` : ""}` : "";
  return `<tr>${name}<td><b style="color:${ctx.palette[run.status] ?? "#94a3b8"}">${esc(state)}</b>${window}${applied ? `<div class="k">applied: ${esc(applied)}</div>` : ""}${pairing(row, run)}<div class="steps">${chips}</div></td></tr>`;
}

/** The panel a clicked merge opens: its commit, where the Board moved it, and each tied DAG's run with its steps, pairing and failure. */
export function mergePanel(row: LedgerRow, ctx: PanelCtx): string {
  const repo = row.pr?.repo ?? "trantor", who = row.tasks[0] ? ctx.task(row.tasks[0]) : "pin bump", writer = ctx.ties.find((t) => t.role === "writer");
  const bump = row.appliedBy ? ctx.by(row.appliedBy) : undefined;
  const board = writer ? `${esc(ctx.from)} → ${esc(ctx.to)}: ${esc(writer.dag)} wrote ${esc(ctx.event)}` : `${esc(ctx.from)} → ${esc(ctx.to)}`;
  const other = cross(row)
    ? `<tr><td>Other repo</td><td>Its merge starts no run here. ${bump ? `The pin bump ${esc(sha7(bump))} applied it at ${esc(ctx.hm(bump.at))}.` : "It applies when the pin bump merges."}</td></tr>`
    : "";
  return `<span class="x">✕</span><div class="k">${row.applies?.length ? "pin bump" : `merge to ${esc(repo)}`} · ${esc(ctx.hm(row.at))}</div><h2>${who}</h2>
    <table><tr><td>Commit</td><td>${esc(repo)} #${row.pr?.number ?? "?"} · ${esc(sha7(row))}</td></tr>
    <tr><td>Board</td><td>${board}</td></tr>${other}${ctx.ties.map((t) => tieRow(row, t, ctx)).join("")}</table>
    ${failHtml(row, ctx, "note")}${rerunHtml(row, ctx)}`;
}

const MARK = { pass: "✓", warn: "⚠", fail: "✕" } as const;
const COMMIT_KEYS = '[runs.commit]\nafter = "AFTER"\nbefore = "BEFORE"\nforce = "FORCE"';

/** The doctor's verdict on the contract, in the Ledger's banner: green when every check passes, amber for a cue with no commit key, red for a failure. */
export function bannerOf(report: ContractReport | null): Banner | null {
  if (!report?.checks.length) return null;
  const failed = report.checks.filter((c) => c.status === "fail");
  if (failed.length) return { tone: "fail", head: `✕ doctor · ${failed.length} contract check${failed.length > 1 ? "s fail" : " fails"}`, sub: failed.map((c) => c.check).join(", ") };
  if (report.checks.some((c) => c.status === "warn")) return { tone: "warn", head: "⚠ doctor · no commit key declared", sub: "runs pair with merges by time" };
  return { tone: "ok", head: "✓ doctor · contract matches runs", sub: "writers, cues and commit keys" };
}

const verdict = (b: Banner | null) => (b ? b.head.replace(/^\S+ doctor · /, "").replace(/^./, (c) => c.toUpperCase()) : "No contract to check");

/** The banner's tip: every check with its mark and reason, and the keys a cue without one should declare. */
export function doctorTip(report: ContractReport): string {
  const banner = bannerOf(report);
  return `<div class="k">starpulse doctor · contract</div><div class="n">${esc(verdict(banner))}</div>${report.checks.map((c) => `<div>${MARK[c.status]} ${esc(c.check)} — ${esc(c.reason)}</div>`).join("")}${report.checks.some((c) => c.status === "warn") ? `<div class="k">Each run pairs with the newest merge before it started (dashed). Declare the commit keys:</div><pre>${esc(COMMIT_KEYS)}</pre>` : ""}`;
}
/** The merge a view is about: the hovered one, else the open one, else the newest merge of the main repository. */
export const focusRow = (hovered: LedgerRow | null, selected: LedgerRow | null, rows: readonly LedgerRow[]): LedgerRow | undefined => hovered ?? selected ?? rows.find((r) => !cross(r));

/** A merge's state for each step of a DAG's template, or null when it has no run of it. */
export function stepStates(row: LedgerRow | undefined, dag: string, steps: readonly string[]): Record<string, RunStatus> | null {
  const run = row?.runs[dag];
  return run ? Object.fromEntries(steps.map((n) => [n, stepState(run, n, steps)])) : null;
}

/** One tied DAG's status line for a merge, coloured by its run's state. */
function runRow(row: LedgerRow, tie: Tie, ctx: PanelCtx): string {
  const line = statusLine(row, tie, row.runs[tie.dag], { event: ctx.event, now: ctx.now, hm: ctx.hm, optional: ctx.optional[tie.dag] ?? new Set(), by: ctx.by });
  return `<div style="color:${line.state ? ctx.palette[line.state] ?? "#94a3b8" : "#94a3b8"}">${esc(tie.dag)}: ${esc(line.main)}${line.sub ? ` <span class="k">· ${esc(line.sub)}</span>` : ""}</div>`;
}

/** A merge row's tip: the commit, the task, each tied DAG's status line and its failures. */
export function mergeTip(row: LedgerRow, ctx: PanelCtx): string {
  const repo = row.pr?.repo ?? "trantor";
  return `<div class="k">${row.applies?.length ? "pin bump" : `merge to ${esc(repo)}`} · ${esc(ctx.hm(row.at))}${row.pr ? ` · #${row.pr.number}` : ""} · ${esc(sha7(row))}</div><div class="n">${esc(row.tasks[0] ?? "pin bump")}</div>`
    + `${ctx.ties.map((t) => runRow(row, t, ctx)).join("")}${failHtml(row, ctx, "k")}`
    + `${cross(row) ? `<div class="k">another repo's merge: nothing applies until the pin bump</div>` : ""}<div class="k">click for its runs</div>`;
}

/** A template step's tip: what it follows, and its state in the merge in view. */
export function stepTip(dag: string, step: string, deps: readonly string[], row: LedgerRow | undefined, ctx: PanelCtx): string {
  const state = stepStates(row, dag, ctx.steps[dag] ?? [step])?.[step];
  const read = row && state ? `${esc(state.replace("_", " "))} in the ${esc(ctx.hm(row.at))} merge (${esc(sha7(row))})` : "";
  return `<div class="k">step of ${esc(dag)}${deps.length ? ` · after ${deps.map(esc).join(", ")}` : ""}</div><div class="n">${esc(step)}</div>${read}<div class="k">hover a merge to see its run here · click for the DAG</div>`;
}

const list = (xs: readonly string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}`);

/** The junction's tip: how many merges the last hour held, and what a merge sets going. */
export function junctionTip(rows: readonly LedgerRow[], ctx: PanelCtx): string {
  const hour = rows.filter((r) => r.at > ctx.now - 3600).length, writer = ctx.ties.find((t) => t.role === "writer"), cued = ctx.ties.filter((t) => t.role === "cue").map((t) => t.dag);
  return `<div class="k">merge to main · ${hour} in the last hour</div><div class="n">A PR merges</div>`
    + (writer ? `${esc(writer.dag)} runs on the ${esc(writer.on)} and writes ${esc(ctx.event)}, moving the task ${esc(ctx.from)} → ${esc(ctx.to)}. ` : "")
    + (cued.length ? `The merge also cues ${esc(list(cued))}.` : "");
}

/** What a Ledger's own marks stand for at a point: a template's step, the junction, the doctor's banner or a merge row. */
export type LedgerHit = { kind: "lstep"; o: GNode } | { kind: "ljunction"; o: LedgerView } | { kind: "ldoctor"; o: ContractReport } | { kind: "lrow"; o: LedgerRow };
/** Where the banner was drawn, in world units, and the report it states. */
export interface DoctorBox { x0: number; y0: number; x1: number; y1: number; report: ContractReport }

/** What the Ledger draws at a world point: a template's step, then the junction, the doctor's banner and a merge row; null off the Ledger. `px` is a screen size in world units. */
export function ledgerHit(scene: Pick<Scene, "stars" | "fold">, doctor: DoctorBox | null, x: number, y: number, px: (n: number) => number, shown: readonly { row: LedgerRow; y: number }[]): LedgerHit | null {
  const led = scene.fold?.ledger;
  if (!led) return null;
  for (const s of Object.values(scene.stars)) for (const n of s.glyph.nodes) if (Math.hypot(s.x + n.x - x, s.y + n.y - y) < Math.max(6, px(8))) return { kind: "lstep", o: n };
  if (Math.hypot(led.J.x - x, led.J.y - y) < Math.max(10, px(12))) return { kind: "ljunction", o: led };
  if (doctor && x >= doctor.x0 && x <= doctor.x1 && y >= doctor.y0 && y <= doctor.y1) return { kind: "ldoctor", o: doctor.report };
  const g = led.grid;
  if (!g) return null;
  const left = Math.min(g.label.x, led.J.x) - px(6), right = led.cols[led.cols.length - 1].x1;
  if (y < g.top || y > g.top + g.view) return null;
  for (const r of shown) if (x >= left && x <= right && Math.abs(y - r.y) <= g.rh / 2) return { kind: "lrow", o: r.row };
  return null;
}
