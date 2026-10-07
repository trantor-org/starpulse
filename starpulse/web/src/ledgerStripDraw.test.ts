import { describe, expect, it } from "vitest";
import type { Ink } from "./ledgerRows";
import { drawStrip, type StripFrame } from "./ledgerStripDraw";
import { stripLabel, stripMarks } from "./ledgerStrip";
import type { LedgerRow, MergeStrip } from "./types";

const NOW = Date.UTC(2026, 9, 7, 22, 0) / 1000;
const row = (n: number, over: Partial<LedgerRow> = {}): LedgerRow => ({ key: `m${n}`, at: NOW - n * 300, tasks: [], runs: {}, fails: {}, pinned: false, ...over });
const PALETTE = { succeeded: "#34d399", failed: "#fb7185" };
const data: MergeStrip = { since: NOW - 86400, bucket: 900, buckets: Array.from({ length: 96 }, () => ({ merges: 0, failed: 0, reruns: 0 })) };
data.buckets[95] = { merges: 3, failed: 1, reruns: 1 };
data.buckets[40] = { merges: 1, failed: 0, reruns: 0 };

function recorder() {
  const texts: { s: string; x: number; y: number; col: string; align?: string }[] = [], strokes: { pts: { x: number; y: number }[]; col: string }[] = [], stars: { x: number; y: number; col: string }[] = [], rects: { x0: number; x1: number }[] = [];
  const ink: Ink = {
    text: (s, x, y, _size, col, align) => void texts.push({ s, x, y, col, align }), fit: (s) => s, width: (s) => s.length * 6,
    stroke: (pts, col) => void strokes.push({ pts, col }), circle: () => {}, dot: () => {}, arc: () => {}, pulse: () => {},
    star4: (x, y, _r, col) => void stars.push({ x, y, col }), rect: (b) => void rects.push(b), clip: (_b, draw) => draw(),
  };
  return { ink, texts, strokes, stars, rects };
}

const strip = { x0: 100, x1: 1060, y: 900, h: 18 };
const frame = (over: Partial<StripFrame> = {}): StripFrame => ({
  led: { grid: { strip } } as StripFrame["led"], data, pins: [], inView: [row(0), row(1), row(7)], loaded: 20, now: NOW, mode: "24", px: (n) => n, palette: PALETTE, ...over,
});
const verticals = (r: ReturnType<typeof recorder>) => r.strokes.filter((s) => s.pts.length === 2 && s.pts[0].x === s.pts[1].x && Math.abs(s.pts[0].y - s.pts[1].y) === strip.h);

describe("drawStrip", () => {
  it("captions the day's merge count and names the range in view and how many are loaded", () => {
    const r = recorder(), f = frame();

    drawStrip(r.ink, f);

    expect(r.texts.find((t) => t.s === "last 24 h · 4 merges")).toMatchObject({ x: strip.x0, align: "left" });
    expect(r.texts.find((t) => t.s === stripLabel(f.inView, 20, 4, "24"))).toMatchObject({ x: strip.x1, align: "right" });
  });

  it("tints the span in view and draws a tick for each quarter-hour with merges, red where a workflow failed", () => {
    const r = recorder(), f = frame(), m = stripMarks(data, [], NOW, strip.x0, strip.x1);

    drawStrip(r.ink, f);

    expect(verticals(r).map((s) => [s.pts[0].x, s.col.includes("251,113,133")])).toEqual(m.ticks.map((t) => [t.x, t.failed]));
    expect(r.rects).toHaveLength(1);
    expect(r.rects[0]).toMatchObject({ x0: m.x(NOW - 7 * 300) - 3, x1: m.x(NOW) + 3 });
  });

  it("stars each unresolved merge above the strip and marks the forced reruns under it", () => {
    const r = recorder(), pin = row(7, { pinned: true }), m = stripMarks(data, [pin], NOW, strip.x0, strip.x1);

    drawStrip(r.ink, frame({ pins: [pin] }));

    expect(r.stars).toEqual([{ x: m.pins[0], y: strip.y - strip.h / 2 - 6, col: PALETTE.failed }]);
    expect(r.texts.find((t) => t.s === "↻")).toMatchObject({ x: m.reruns[0].x, y: expect.any(Number) });
  });

  it("labels the hours three apart along the baseline, in the Admin view's clock", () => {
    const r = recorder();

    drawStrip(r.ink, frame());

    const hours = r.texts.filter((t) => /^\d\d:00$/.test(t.s)).map((t) => t.s);
    expect(hours.length).toBeGreaterThanOrEqual(8);
    expect(hours.every((h) => Number(h.slice(0, 2)) % 3 === 0)).toBe(true);
  });
});
