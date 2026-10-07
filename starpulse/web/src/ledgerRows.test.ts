import { describe, expect, it } from "vitest";
import { build } from "./scene";
import { merge, Moves } from "./sky";
import { AMBER, CROSS, drawRows, type Ink, type RowsFrame } from "./ledgerRows";
import { optionalSteps } from "./ledger";
import { ledgerLevel } from "./levels";
import type { Cue, Dag, LedgerRow, LedgerRun, Machine, Snapshot } from "./types";

const PALETTE: Record<string, string> = { running: "#fbbf24", queued: "#93c5fd", succeeded: "#34d399", failed: "#fb7185", aborted: "#94a3b8", skipped: "#64748b", not_started: "#334155", waiting: "#c084fc" };
const iso = (s: number) => new Date(s * 1000).toISOString().replace(/\.\d+Z$/, "Z");
const dag = (name: string, steps: string[]): Dag => ({ name, status: "succeeded", runId: "r", startedAt: "", finishedAt: "", steps: steps.map((n, i) => ({ name: n, depends: i ? [steps[i - 1]] : [], status: "succeeded" })) });
const machine = (): Machine => ({
  states: ["review", "done"].map((id, i) => ({ id, name: id, initial: !i, final: !!i })),
  transitions: [{ source: "review", target: "done", event: "MERGED" }],
  writers: { MERGED: [{ actor: "main-follow", trigger: "push" }] }, dagActors: ["main-follow"], mainLine: ["review", "done"],
} as Machine);
const cues: Cue[] = [{ dag: "apply-on-merge", event: "MERGED", state: "done", on: "each merge", resolves: "forced" }];
const run = (over: Partial<LedgerRun> = {}): LedgerRun => ({ runId: "r", status: "succeeded", startedAt: iso(1000), finishedAt: iso(1042), steps: { build: "succeeded", apply: "succeeded" }, step: "", inferred: false, ambiguous: 0, ...over });
const row = (key: string, at: number, over: Partial<LedgerRow> = {}): LedgerRow => ({ key, at, tasks: [`TASK-${at}`], sha: key.padEnd(10, "0"), pr: { repo: "trantor", number: at, url: "u" }, runs: {}, fails: {}, pinned: false, ...over });

/** What the recorder saw: every text with its colour, every stroke with its colour and dash, and the circles and pulses. */
function recorder() {
  const texts: { s: string; x: number; y: number; col: string }[] = [], strokes: { pts: { x: number; y: number }[]; col: string; dash?: number[] }[] = [];
  const circles: { x: number; y: number; col: string }[] = [], pulses: { x: number; y: number; age: number }[] = [];
  const ink: Ink = {
    text: (s, x, y, _size, col) => void texts.push({ s, x, y, col }),
    fit: (s) => s,
    stroke: (pts, col, _w, dash) => void strokes.push({ pts, col, dash }),
    circle: (x, y, _r, col) => void circles.push({ x, y, col }),
    dot: () => {},
    pulse: (x, y, _r, age) => void pulses.push({ x, y, age }),
  };
  return { ink, texts, strokes, circles, pulses };
}

function frame(rows: LedgerRow[], over: Partial<RowsFrame> = {}): RowsFrame {
  const snap: Snapshot = {
    graphs: ["board"], flows: [{ name: "board", agents: [], machine: machine() }], cues, ledgers: { MERGED: rows }, settled: {}, error: null, now: 2000,
    dags: [dag("main-follow", ["only"]), dag("apply-on-merge", ["build", "apply"])],
    domains: [{ name: "Board", dags: [{ name: "main-follow", runSafe: false }, { name: "apply-on-merge", runSafe: false }] }],
  };
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 2000);
  const src = { flows: [S.flows.board], cues: S.cues }, level = ledgerLevel(src, "MERGED")!;
  const scene = build({ S, moves, W: 1920, H: 1080, T: 2000 }, level), led = scene.fold!.ledger!;
  return {
    led, glyphs: Object.fromEntries(Object.entries(scene.stars).map(([n, s]) => [n, s.glyph])),
    ctx: { event: "MERGED", now: 1100, hm: (s) => `t${s % 1000}`, by: (k) => rows.find((r) => r.key === k) },
    optional: Object.fromEntries(led.cols.map((c) => [c.dag, optionalSteps(rows, c.dag)])),
    px: (n) => n, palette: PALETTE, clock: 5, age: () => undefined, ...over,
  };
}

describe("drawRows", () => {
  it("writes each row's time and task, then every template's status line coloured by the run's state", () => {
    const r = recorder(), rows = [row("aaa", 990, { runs: { "main-follow": run(), "apply-on-merge": run({ status: "failed" }) }, fails: { "apply-on-merge": { runId: "r", step: "apply", startedAt: iso(1000), finishedAt: iso(1042), resolves: "forced", resolved: null } } })];

    drawRows(r.ink, frame(rows));

    const by = (s: string) => r.texts.find((t) => t.s === s)!;
    expect(by("t990  TASK-990")).toBeDefined();
    expect(by("trantor #990 · aaa0000")).toBeDefined();
    expect([by("✓ 42 s").col, by("✕ apply · 42 s").col]).toEqual([expect.stringContaining("52,211,153"), expect.stringContaining("251,113,133")]);
    expect(by("MERGED t990")).toBeDefined();
  });

  it("draws one mini step graph per run, its steps ringed in the step's own colour", () => {
    const r = recorder(), rows = [row("aaa", 990, { runs: { "apply-on-merge": run({ steps: { build: "succeeded", apply: "failed" } }) } })];

    drawRows(r.ink, frame(rows));

    expect(r.circles.map((c) => c.col).filter((c) => c.includes("52,211,153") || c.includes("251,113,133")).length).toBe(2);
  });

  it("boxes a run paired by time in a dashed line, amber when another merge landed in its window", () => {
    const r = recorder(), rows = [
      row("key", 990, { runs: { "apply-on-merge": run() } }),
      row("inf", 980, { runs: { "apply-on-merge": run({ inferred: true }) } }),
      row("amb", 970, { runs: { "apply-on-merge": run({ inferred: true, ambiguous: 1 }) } }),
    ];

    drawRows(r.ink, frame(rows));

    const dashed = r.strokes.filter((s) => s.dash && s.pts.length === 5);
    expect(dashed.map((s) => s.col.includes("245,158,11"))).toEqual([false, true]);
    expect(r.texts.find((t) => t.s.startsWith("≈ 2 in window"))!.col).toContain("245,158,11");
    expect(AMBER).toBe("#f59e0b");
  });

  it("puts another repository's merge on the cross lane and links it to the pin-bump row that applies it", () => {
    const r = recorder(), f = frame([row("bmp", 990, { tasks: [], runs: { "main-follow": run(), "apply-on-merge": run() } }), row("kid", 980, { appliedBy: "bmp", pr: { repo: "starpulse", number: 7, url: "u" } })]);

    drawRows(r.ink, f);

    const g = f.led.grid!, lane = g.lane;
    expect(r.circles.some((c) => c.x === lane && c.y === g.rows[1].y && c.col.includes("192,132,252"))).toBe(true);
    expect(r.texts.find((t) => t.s === "applied by its pin bump bmp0000")).toBeDefined();
    const link = r.strokes.find((s) => s.dash && s.pts.length === 2 && s.pts[0].x === lane && s.pts[0].y === g.rows[1].y)!;
    expect(link.pts[1].y).toBe(g.rows[0].y);
    expect(link.col).toContain("192,132,252");
    expect(r.texts.some((t) => t.s === "pin bump")).toBe(true);
    expect(CROSS).toBe("#c084fc");
  });

  it("leaves a cross row unlinked while no shown row has pin-bumped it", () => {
    const r = recorder();

    drawRows(r.ink, frame([row("kid", 980, { appliedBy: null, pr: { repo: "starpulse", number: 7, url: "u" } })]));

    expect(r.strokes.filter((s) => s.dash && s.pts.length === 2)).toEqual([]);
    expect(r.texts.some((t) => t.s === "waits for its pin bump")).toBe(true);
    expect(r.texts.some((t) => t.s === "pin bump")).toBe(false);
  });

  it("outlines the row that is lit (hovered or open) and no other", () => {
    const r = recorder(), rows = [row("aaa", 990), row("bbb", 980)], outlines = () => r.strokes.filter((s) => s.pts.length === 5 && s.col.includes("251,191,36"));

    drawRows(r.ink, frame(rows));
    expect(outlines()).toHaveLength(0);

    drawRows(r.ink, frame(rows, { lit: "bbb" }));
    const [box] = outlines(), g = frame(rows).led.grid!;
    expect(outlines()).toHaveLength(1);
    expect([box.pts[0].y, box.pts[2].y]).toEqual([g.rows[1].y - g.rh / 2, g.rows[1].y + g.rh / 2]);
  });

  it("rings a row that just arrived, fades it in and lowers it from a row above until it settles", () => {
    const fresh = recorder(), settled = recorder(), rows = [row("aaa", 990, { runs: { "main-follow": run() } })];
    const alpha = (c: string) => Number(c.match(/,([\d.]+)\)$/)![1]);

    drawRows(fresh.ink, frame(rows, { age: () => 0.1 }));
    drawRows(settled.ink, frame(rows));

    const a = fresh.texts.find((t) => t.s === "t990  TASK-990")!, b = settled.texts.find((t) => t.s === "t990  TASK-990")!;
    expect(fresh.pulses.length).toBeGreaterThan(0);
    expect(settled.pulses.length).toBe(0);
    expect(a.y).toBeLessThan(b.y);
    expect(alpha(a.col)).toBeLessThan(alpha(b.col));
  });
});
