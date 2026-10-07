import { describe, expect, it } from "vitest";
import { build } from "./scene";
import { merge, Moves } from "./sky";
import { optionalSteps } from "./ledger";
import { ledgerLevel } from "./levels";
import { newScroll, place, take } from "./ledgerScroll";
import { bannerOf, ledgerHit, mergePanel, type DoctorBox, type PanelCtx } from "./ledgerPanel";
import type { ContractReport, Cue, Dag, LedgerRow, LedgerRun, Machine, Snapshot } from "./types";

const iso = (s: number) => new Date(s * 1000).toISOString().replace(/\.\d+Z$/, "Z");
const dag = (name: string, steps: string[]): Dag => ({ name, status: "succeeded", runId: "r", startedAt: "", finishedAt: "", steps: steps.map((n, i) => ({ name: n, depends: i ? [steps[i - 1]] : [], status: "succeeded" })) });
const machine = (): Machine => ({
  states: ["review", "done"].map((id, i) => ({ id, name: id, initial: !i, final: !!i })),
  transitions: [{ source: "review", target: "done", event: "MERGED" }],
  writers: { MERGED: [{ actor: "main-follow", trigger: "push" }] }, dagActors: ["main-follow"], mainLine: ["review", "done"],
} as Machine);
const cues: Cue[] = [{ dag: "apply-on-merge", event: "MERGED", state: "done", on: "each merge", resolves: "forced" }];
const run = (over: Partial<LedgerRun> = {}): LedgerRun => ({ runId: "r", status: "succeeded", startedAt: iso(1000), finishedAt: iso(1042), steps: { build: "succeeded", apply: "succeeded" }, step: "", inferred: false, ambiguous: 0, ...over });
const failed = run({ status: "failed", steps: { build: "succeeded", apply: "failed" } });
const ROWS: LedgerRow[] = [
  { key: "aaa", at: 990, tasks: ["TASK-1"], sha: "aaa0000000", pr: { repo: "trantor", number: 1, url: "u" }, runs: { "main-follow": run({ steps: {} }), "apply-on-merge": failed }, fails: { "apply-on-merge": { runId: "r", step: "apply", startedAt: iso(1000), finishedAt: iso(1042), resolves: "forced", resolved: null } }, pinned: false },
  { key: "bbb", at: 980, tasks: ["TASK-2"], sha: "bbb0000000", pr: { repo: "trantor", number: 2, url: "u" }, runs: { "apply-on-merge": run() }, fails: {}, pinned: false },
];

/** The Ledger the page draws for the rows, as the renderer builds it. */
function ledger(rows: LedgerRow[]) {
  const snap: Snapshot = {
    graphs: ["board"], flows: [{ name: "board", agents: [], machine: machine() }], cues, ledgers: { MERGED: rows }, settled: {}, error: null, now: 2000,
    dags: [dag("main-follow", ["only"]), dag("apply-on-merge", ["build", "apply"])],
    domains: [{ name: "Board", dags: [{ name: "main-follow", runSafe: false }, { name: "apply-on-merge", runSafe: false }] }],
  };
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 2000);
  const src = { flows: [S.flows.board], cues: S.cues }, scene = build({ S, moves, W: 1920, H: 1080, T: 2000 }, ledgerLevel(src, "MERGED")!);
  const led = scene.fold!.ledger!, byKey = new Map(rows.map((r) => [r.key, r]));
  const ctx: PanelCtx = {
    event: "MERGED", from: "Review", to: "Done", ties: led.cols, steps: Object.fromEntries(led.cols.map((c) => [c.dag, scene.stars[c.dag].glyph.nodes.map((n) => n.name)])),
    optional: Object.fromEntries(led.cols.map((c) => [c.dag, optionalSteps(rows, c.dag)])), palette: { succeeded: "#34d399", failed: "#fb7185", not_started: "#334155" },
    now: 2000, hm: (s) => `t${s % 1000}`, by: (k) => byKey.get(k), task: (id) => id,
  };
  return { scene, led, ctx, shown: place(take(newScroll(), rows, led.grid!), led.grid!) };
}
const px = (n: number) => n;

describe("clicking a merge row on the Ledger", () => {
  it("lands on the row under the pointer, and its panel lists each cued run with its step states and failure text", () => {
    const { scene, led, ctx, shown } = ledger(ROWS), at = shown[0];

    const hit = ledgerHit(scene, null, led.J.x + 40, at.y, px, shown);

    expect(hit).toEqual({ kind: "lrow", o: ROWS[0] });
    const html = mergePanel((hit as { o: LedgerRow }).o, ctx);
    expect(html).toContain("apply-on-merge");
    expect(html).toMatch(/title="failed">apply</);
    expect(html).toMatch(/title="succeeded">build</);
    expect(html).toContain("apply-on-merge ✕ apply: unresolved, clears on a forced rerun");
  });

  it("lands on the second row for a point at its height, and on nothing between the rows' gutter and the margin", () => {
    const { scene, led, shown } = ledger(ROWS);

    expect(ledgerHit(scene, null, led.J.x + 40, shown[1].y, px, shown)).toEqual({ kind: "lrow", o: ROWS[1] });
    expect(ledgerHit(scene, null, led.cols[led.cols.length - 1].x1 + 200, shown[1].y, px, shown)).toBeNull();
  });

  it("lands on a template's step and the junction before the rows", () => {
    const { scene, led, shown } = ledger(ROWS), star = scene.stars["apply-on-merge"], node = star.glyph.nodes[0];

    expect(ledgerHit(scene, null, star.x + node.x, star.y + node.y, px, shown)).toEqual({ kind: "lstep", o: node });
    expect(ledgerHit(scene, null, led.J.x, led.J.y, px, shown)).toEqual({ kind: "ljunction", o: led });
  });
});

describe("the doctor banner on the Ledger", () => {
  const FAIL: ContractReport = { ok: false, checks: [{ check: "cue:apply-on-merge", status: "fail", reason: "apply-on-merge declares no parameter for [runs.commit] after=AFTER" }] };

  it("states a failing contract report, and a point on it lands on the report", () => {
    const { scene, led, shown } = ledger(ROWS), box: DoctorBox = { x0: led.J.x - 300, y0: led.bus - 20, x1: led.J.x - 16, y1: led.bus + 20, report: FAIL };

    expect(bannerOf(FAIL)).toMatchObject({ tone: "fail", head: "✕ doctor · 1 contract check fails", sub: "cue:apply-on-merge" });
    expect(ledgerHit(scene, box, led.J.x - 100, led.bus, px, shown)).toEqual({ kind: "ldoctor", o: FAIL });
    expect(ledgerHit(scene, null, led.J.x - 100, led.bus, px, shown)).toBeNull();
  });
});
