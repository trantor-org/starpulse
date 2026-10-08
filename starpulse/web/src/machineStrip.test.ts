import { describe, expect, it } from "vitest";
import { stripLabel, stripScale, tickAt, ticks, viewSpan } from "./machineStrip";
import { windowOf } from "./machineScroll";
import type { MachineEntry } from "./api";

const NOW = 100000, scale = stripScale(300, 1100, NOW);
const entry = (at: number, row = "m", over: Partial<MachineEntry> = {}): MachineEntry => ({ at, machine: row, row, from: { machine: "ip", state: "pr_opened" }, dag: null, ...over });

describe("the machine ledger's 24 h strip", () => {
  it("maps the last 24 hours across the strip, the oldest at its left end and now at its right", () => {
    expect(scale.x(NOW - 86400)).toBe(300);
    expect(scale.x(NOW)).toBe(1100);
    expect(scale.x(NOW - 43200)).toBe(700);
  });

  it("draws a tick for each entry of a row on the ledger, in the 24 hours, and none for the rest", () => {
    const found = ticks([entry(NOW - 100, "a"), entry(NOW - 90000, "a"), entry(NOW - 50, "gone"), entry(NOW - 43200, "b")], ["a", "b"], scale);
    expect(found.map((t) => [t.entry.row, t.x])).toEqual([["a", expect.closeTo(1100 - 800 / 864, 5)], ["b", 700]]);
  });

  it("spans the rows in view from their oldest activity to their newest, leaving out a row quiet for the whole 24 hours", () => {
    expect(viewSpan([NOW - 100, NOW - 4000, null, NOW - 90000], NOW - 86400)).toEqual({ from: NOW - 4000, to: NOW - 100 });
    expect(viewSpan([null, NOW - 90000], NOW - 86400)).toBeNull();
    expect(viewSpan([], NOW - 86400)).toBeNull();
  });

  it("shades one continuous stretch: no row outside the view was active inside what it shades", () => {
    const lasts = Array.from({ length: 40 }, (_, i) => NOW - 600 * i * (1 + i / 10)), rows = lasts.map(() => ({ h: 100 }));
    for (const scroll of [0, 130, 950, 2400, 3600]) {
      const { inView } = windowOf(rows, scroll, { h: 400, fs: 1 }), span = viewSpan(inView.map((i) => lasts[i]), NOW - 86400);
      if (!span) {
        expect(inView.every((i) => lasts[i] <= NOW - 86400)).toBe(true); // rows older than the 24 hours shade nothing
        continue;
      }
      const outside = lasts.filter((_, i) => !inView.includes(i) && lasts[i] > NOW - 86400);
      expect(outside.every((t) => t < span.from || t > span.to)).toBe(true);
    }
  });

  it("finds the tick under the pointer within four pixels, the nearest of two", () => {
    const found = ticks([entry(NOW - 43200, "a"), entry(NOW - 43200 + 600, "b")], ["a", "b"], scale);
    expect(tickAt(found, 702)?.entry.row).toBe("a");
    expect(tickAt(found, 708.5)?.entry.row).toBe("b");
    expect(tickAt(found, 720)).toBeNull();
  });

  it("reads the span in view and how many of the machines are loaded", () => {
    const hm = (s: number) => `t${s - NOW}`;
    expect(stripLabel({ from: NOW - 4000, to: NOW - 100 }, 20, 34, hm)).toBe("t-4000–t-100 in view · 20 of 34 loaded");
    expect(stripLabel(null, 20, 34, hm)).toBe("20 of 34 loaded");
  });
});
