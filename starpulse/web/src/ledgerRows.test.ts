import { describe, expect, it } from "vitest";
import { build } from "./scene";
import { merge, Moves } from "./sky";
import { AMBER, CROSS, drawRows, type Box, type Ink, type RowsFrame } from "./ledgerRows";
import { newScroll, place, take, type Scroll } from "./ledgerScroll";
import { pinsOf, portOf, withPins } from "./ledgerPins";
import { optionalSteps } from "./ledger";
import { ledgerLevel } from "./levels";
import type { Cue, Dag, LedgerRow, LedgerRun, Machine, Snapshot } from "./api";

const PALETTE: Record<string, string> = { running: "#fbbf24", queued: "#93c5fd", succeeded: "#34d399", failed: "#fb7185", aborted: "#94a3b8", skipped: "#64748b", not_started: "#334155", waiting: "#c084fc" };
const iso = (s: number) => new Date(s * 1000).toISOString().replace(/\.\d+Z$/, "Z");
const dag = (name: string, steps: string[]): Dag => ({ name, status: "succeeded", runId: "r", startedAt: "", finishedAt: "", steps: steps.map((n, i) => ({ name: n, depends: i ? [steps[i - 1]] : [], status: "succeeded", kind: null })) });
const machine = (): Machine => ({
  states: ["review", "done"].map((id, i) => ({ id, name: id, initial: !i, final: !!i })),
  transitions: [{ source: "review", target: "done", event: "MERGED" }],
  writers: { MERGED: [{ actor: "main-follow", trigger: "push" }] }, dagActors: ["main-follow"], mainLine: ["review", "done"],
} as Machine);
const cues: Cue[] = [{ dag: "apply-on-merge", event: "MERGED", state: "done", on: "each merge", resolves: "forced" }];
const run = (over: Partial<LedgerRun> = {}): LedgerRun => ({ runId: "r", status: "succeeded", startedAt: iso(1000), finishedAt: iso(1042), steps: { build: "succeeded", apply: "succeeded" }, step: "", inferred: false, ambiguous: 0, ...over });
const row = (key: string, at: number, over: Partial<LedgerRow> = {}): LedgerRow => ({ key, at, tasks: [`TASK-${at}`], sha: key.padEnd(10, "0"), pr: { repo: "trantor", number: at, url: "u" }, runs: {}, fails: {}, pinned: false, ...over });

/** What the recorder saw: every text with its colour and whether it was drawn under the clip, every stroke with its colour and dash, and the circles and pulses. */
function recorder() {
  const texts: { s: string; x: number; y: number; col: string; clipped: boolean }[] = [], strokes: { pts: { x: number; y: number }[]; col: string; dash?: number[] }[] = [];
  const stars: { x: number; y: number; col: string }[] = [], circles: { x: number; y: number; col: string }[] = [], pulses: { x: number; y: number; age: number }[] = [], clips: Box[] = [], rects: Box[] = [];
  let clipped = false;
  const ink: Ink = {
    text: (s, x, y, _size, col) => void texts.push({ s, x, y, col, clipped }),
    fit: (s) => s,
    width: (s) => s.length * 6,
    stroke: (pts, col, _w, dash) => void strokes.push({ pts, col, dash }),
    circle: (x, y, _r, col) => void circles.push({ x, y, col }),
    dot: () => {},
    star4: (x, y, _r, col) => void stars.push({ x, y, col }),
    arc: () => {},
    rect: (b) => void rects.push(b),
    pulse: (x, y, _r, age) => void pulses.push({ x, y, age }),
    clip: (b, draw) => {
      clips.push(b);
      clipped = true;
      draw();
      clipped = false;
    },
  };
  return { ink, texts, strokes, circles, pulses, clips, rects, stars };
}

/** `rows` loaded into a scroll under the level's viewport, `y` rows' worth down it. */
const scrolled = (led: RowsFrame["led"], rows: LedgerRow[], y = 0, more?: boolean): Scroll => {
  const sc = take(newScroll(), rows, led.grid!);
  return { ...sc, y, ty: y, ...(more === undefined ? {} : { more }) };
};

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
    led, scroll: scrolled(led, rows), glyphs: Object.fromEntries(Object.entries(scene.stars).map(([n, s]) => [n, s.glyph])),
    ctx: { event: "MERGED", now: 1100, hm: (s) => `t${s % 1000}`, by: (k) => rows.find((r) => r.key === k) },
    optional: Object.fromEntries(led.cols.map((c) => [c.dag, optionalSteps(rows, c.dag)])),
    pins: { shown: [], all: [], below: 0, failed: 0 }, px: (n) => n, palette: PALETTE, clock: 5, age: () => undefined, ...over,
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

  it("labels a row as the mockup does: time and task with its PR and commit after them, the task's title under them", () => {
    const r = recorder(), f = frame([row("aaa", 990)], { title: (id) => (id === "TASK-990" ? "Ship the ledger" : undefined) }), y = place(f.scroll, f.led.grid!)[0].y;

    drawRows(r.ink, f);

    const by = (s: string) => r.texts.find((t) => t.s === s)!, head = by("t990  TASK-990");
    expect([head.x, head.y]).toEqual([f.led.grid!.label.x, y - 8]);
    expect(by("trantor #990 · aaa0000").y).toBe(head.y);
    expect(by("trantor #990 · aaa0000").x).toBeGreaterThan(head.x + r.ink.width(head.s, 12.5));
    expect([by("Ship the ledger").x, by("Ship the ledger").y]).toEqual([head.x, y + 9]);
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
    expect(r.circles.some((c) => c.x === lane && c.y === place(f.scroll, g)[1].y && c.col.includes("192,132,252"))).toBe(true);
    expect(r.texts.find((t) => t.s === "applied by its pin bump bmp0000")).toBeDefined();
    const link = r.strokes.find((s) => s.dash && s.pts.length === 2 && s.pts[0].x === lane && s.pts[0].y === place(f.scroll, g)[1].y)!;
    expect(link.pts[1].y).toBe(place(f.scroll, g)[0].y);
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
    const [box] = outlines(), f = frame(rows), g = f.led.grid!, y = place(f.scroll, g)[1].y;
    expect(outlines()).toHaveLength(1);
    expect([box.pts[0].y, box.pts[2].y]).toEqual([y - g.rh / 2, y + g.rh / 2]);
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

  describe("scrolled", () => {
    const many = Array.from({ length: 500 }, (_, i) => row(`m${i}`, 100_000 - i * 60));
    const labels = (r: ReturnType<typeof recorder>) => r.texts.filter((t) => /^t\d+ {2}TASK-/.test(t.s));

    it("draws only the rows inside the viewport and one past each edge, out of five hundred, all under the clip", () => {
      const r = recorder(), f = frame(many), g = f.led.grid!;
      f.scroll = scrolled(f.led, many, 100 * g.rh + 10);

      drawRows(r.ink, f);

      const shown = labels(r), most = g.view / g.rh + 3;
      expect(shown.length).toBeGreaterThanOrEqual(g.view / g.rh);
      expect(shown.length).toBeLessThanOrEqual(most);
      expect(shown.some((t) => t.s.includes(`TASK-${100_000 - 100 * 60}`))).toBe(true);
      expect(shown.some((t) => t.s.includes("TASK-100000"))).toBe(false);
      expect(shown.every((t) => t.clipped)).toBe(true);
      expect(r.clips).toEqual([{ x0: expect.any(Number), y0: g.top, x1: expect.any(Number), y1: g.top + g.view }]);
    });

    it("writes the loading row under the last loaded merge while older ones remain", () => {
      const r = recorder(), f = frame(many.slice(0, 20)), g = f.led.grid!;
      f.scroll = scrolled(f.led, many.slice(0, 20), 21 * g.rh - g.view, true);

      drawRows(r.ink, f);

      expect(r.texts.find((t) => t.s === "loading older merges · 20 at a time")).toMatchObject({ clipped: true });
      expect(r.texts.some((t) => t.s.startsWith("oldest merge"))).toBe(false);
    });

    it("writes the oldest-merge row, with the rows held, once none remain", () => {
      const r = recorder(), f = frame(many.slice(0, 5));

      drawRows(r.ink, f);

      expect(r.texts.find((t) => t.s === "oldest merge in the last 24 h · 5 rows")).toBeDefined();
      expect(r.texts.some((t) => t.s.startsWith("loading"))).toBe(false);
    });

    it("draws a thumb beside the rows and gives its box, and none when every row fits", () => {
      const f = frame(many.slice(0, 40)), g = f.led.grid!;
      f.scroll = scrolled(f.led, many.slice(0, 40), 100, true);

      const hits = drawRows(recorder().ink, f);

      expect(hits.thumb).toMatchObject({ y0: expect.any(Number), y1: expect.any(Number) });
      expect(hits.thumb!.y0).toBeGreaterThanOrEqual(g.top);
      expect(hits.thumb!.y1).toBeLessThanOrEqual(g.top + g.view);
      expect(hits.thumb!.x0).toBeGreaterThan(f.led.cols.at(-1)!.x0);
      expect(drawRows(recorder().ink, frame(many.slice(0, 3))).thumb).toBeNull();
    });

    it("shows the chip back to the newest once scrolled, counting merges that landed since, and none at the top", () => {
      const f = frame(many.slice(0, 40)), up = recorder(), down = recorder(), fresh = recorder();
      expect(drawRows(up.ink, f).chip).toBeNull();
      f.scroll = scrolled(f.led, many.slice(0, 40), 200, true);

      const hits = drawRows(down.ink, f);
      f.scroll = { ...f.scroll, fresh: 2 };
      drawRows(fresh.ink, f);

      expect(down.texts.find((t) => t.s.startsWith("↑"))!.s).toBe("↑ back to newest");
      expect(fresh.texts.find((t) => t.s.startsWith("↑"))!.s).toBe("↑ 2 new merges");
      expect(hits.chip!.x1 - hits.chip!.x0).toBeGreaterThan(0);
      expect(up.texts.some((t) => t.s.startsWith("↑"))).toBe(false);
    });
  });
});

describe("the unresolved band", () => {
  const open = { runId: "r", step: "apply", startedAt: iso(1000), finishedAt: iso(1042), resolves: "forced" as const, resolved: null };
  const pin = (key: string, at: number) => row(key, at, { pinned: true, runs: { "apply-on-merge": run({ status: "failed" }) }, fails: { "apply-on-merge": open } });
  const day = (extra: LedgerRow[]) => [...Array.from({ length: 30 }, (_, i) => row(`r${i}`, 900 - i * 10)), ...extra].sort((a, b) => b.at - a.at);
  /** The Ledger of `rows` as the renderer holds it: the band's pins out of the scrolling list, which sits `y` down. */
  function banded(rows: LedgerRow[], y = 0) {
    const g = frame(rows).led.grid!, pins = pinsOf(rows, [], g.cap), sc = take(withPins(newScroll(), pins), rows, portOf(g, pins.shown.length));
    return frame(rows, { pins, scroll: { ...sc, y, ty: y } });
  }
  const head = (r: ReturnType<typeof recorder>, at: number) => r.texts.find((t) => t.s === `t${at % 1000}  TASK-${at}`);

  it("pins an open failure above the rows under an UNRESOLVED label, and it stays put while the rows scroll beneath", () => {
    const rows = day([pin("bad", 955)]), top = banded(rows), g = top.led.grid!, a = recorder(), b = recorder();

    drawRows(a.ink, top);
    drawRows(b.ink, banded(rows, 6 * g.rh));

    expect(a.texts.find((t) => t.s === "UNRESOLVED · 1 failed run")).toMatchObject({ x: g.label.x, y: g.top - 9, clipped: false });
    expect(head(a, 955)).toMatchObject({ y: g.top + g.rh / 2 - 8, clipped: false });
    expect(a.stars.map((s) => [s.x, s.y])).toEqual([[top.led.J.x, g.top + g.rh / 2]]);
    expect(head(a, 900)!.y).toBeGreaterThan(g.top + g.rh);
    expect(head(b, 955)!.y).toBe(head(a, 955)!.y);
    expect(head(b, 900)).toBeUndefined();
    expect(head(b, 840)!.y).toBeLessThan(head(a, 840)?.y ?? Infinity);
  });

  it("is gone once the snapshot resolves the failure, the merge back among the rows", () => {
    const fixed = row("bad", 955, { runs: { "apply-on-merge": run({ status: "failed" }) }, fails: { "apply-on-merge": { ...open, resolved: { runId: "r2", at: iso(1500) } } } });
    const r = recorder(), f = banded(day([fixed]));

    drawRows(r.ink, f);

    expect(r.texts.some((t) => t.s.startsWith("UNRESOLVED"))).toBe(false);
    expect(head(r, 955)).toMatchObject({ clipped: true, y: f.led.grid!.top + f.led.grid!.rh / 2 - 8 });
  });

  it("counts the pins past its cap as waiting below, and words a forced rerun in progress", () => {
    const g = frame(day([])).led.grid!, rows = day(Array.from({ length: g.cap + 2 }, (_, i) => pin(`p${i}`, 960 + i)));
    const r = recorder(), f = { ...banded(rows), rerunning: "↻ forced rerun running · 12 s" };

    drawRows(r.ink, f);

    expect(r.texts.find((t) => t.s.startsWith("UNRESOLVED"))!.s).toBe(`UNRESOLVED · ${g.cap + 2} failed runs (+2 below)`);
    expect(r.texts.find((t) => t.s === "↻ forced rerun running · 12 s")).toMatchObject({ y: g.top - 9, clipped: false });
  });
});
