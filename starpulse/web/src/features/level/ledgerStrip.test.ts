import { describe, expect, it } from "vitest";
import { PAGE, newScroll, take, type Viewport } from "./ledgerScroll";
import { inView, stripLabel, stripMarks } from "./ledgerStrip";
import type { LedgerRow, MergeStrip } from "../../api";

// 15:00 MST on Oct 7 2026; each merge lands five minutes before the one above it.
const NOW = Date.UTC(2026, 9, 7, 22, 0) / 1000;
const row = (n: number, over: Partial<LedgerRow> = {}): LedgerRow => ({ key: `m${n}`, at: NOW - n * 300, tasks: [], runs: {}, fails: {}, pinned: false, ...over });
const vp: Viewport = { top: 100, view: 272, rh: 34 };
const loaded = (n: number) => take(newScroll(), Array.from({ length: n }, (_, i) => row(i)), vp);

describe("the strip's in-view label", () => {
  it("names the span of the merges in view and how many of the day's are loaded", () => {
    const sc = loaded(PAGE), shown = inView(sc, vp);

    expect(shown).toHaveLength(8);
    expect(stripLabel(shown, sc.rows.length, 96, "24")).toBe("14:25–15:00 in view · 20 of 96 loaded");
  });

  it("tracks the range as the rows scroll", () => {
    const sc = loaded(PAGE), down = { ...sc, y: 340, ty: 340 };

    expect(stripLabel(inView(down, vp), sc.rows.length, 96, "24")).toBe("13:35–14:10 in view · 20 of 96 loaded");
  });

  it("follows the Admin view's clock, and is empty when no merge is in view", () => {
    expect(stripLabel(inView(loaded(PAGE), vp), PAGE, 96, "12")).toBe("2:25 pm–3:00 pm in view · 20 of 96 loaded");
    expect(stripLabel([], 0, 0, "24")).toBe("");
  });
});

describe("the strip's marks", () => {
  const strip: MergeStrip = { since: NOW - 86400, bucket: 900, buckets: Array.from({ length: 96 }, () => ({ merges: 0, failed: 0, reruns: 0 })) };
  strip.buckets[95] = { merges: 3, failed: 1, reruns: 1 };
  strip.buckets[10] = { merges: 1, failed: 0, reruns: 0 };

  it("draws a tick for each bucket with merges, red where one failed, across the day", () => {
    const m = stripMarks(strip, [], NOW, 100, 1060);

    expect(m.ticks.map((t) => [Math.round(t.x), t.merges, t.failed])).toEqual([[Math.round(100 + (10.5 / 96) * 960), 1, false], [Math.round(100 + (95.5 / 96) * 960), 3, true]]);
  });

  it("marks the forced reruns and the pinned merges at the time they happened", () => {
    const m = stripMarks(strip, [row(7, { pinned: true })], NOW, 100, 1060);

    expect(m.reruns).toEqual([{ x: m.ticks[1].x, n: 1 }]);
    expect(m.pins).toEqual([m.x(NOW - 7 * 300)]);
    expect(m.x(NOW)).toBe(1060);
    expect(m.x(NOW - 86400)).toBe(100);
  });

  it("holds the day at the clock rather than at the strip's last send", () => {
    const stale = stripMarks({ ...strip, since: NOW - 86400 - 900 }, [], NOW + 900, 100, 1060);

    expect(stale.ticks.map((t) => t.merges)).toEqual([1, 3]);
    expect(stale.ticks[1].x).toBeLessThanOrEqual(1060);
  });
});
