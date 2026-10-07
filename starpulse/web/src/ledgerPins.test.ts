import { describe, expect, it } from "vitest";
import { PAGE, newScroll, place, take, type Viewport } from "./ledgerScroll";
import { pinsOf, portOf, withPins } from "./ledgerPins";
import type { LedgerFail, LedgerRow } from "./api";

const open = (resolved: LedgerFail["resolved"] = null): LedgerFail => ({ runId: "r", step: "apply", startedAt: "", finishedAt: "", resolves: "forced", resolved });
const row = (n: number, over: Partial<LedgerRow> = {}): LedgerRow => ({ key: `m${n}`, at: 100_000 - n * 60, tasks: [`T-${n}`], runs: {}, fails: {}, pinned: false, ...over });
const pinned = (n: number, dags = ["apply-on-merge"]): LedgerRow => row(n, { pinned: true, fails: Object.fromEntries(dags.map((d) => [d, open()])) });

describe("the unresolved band", () => {
  it("holds the merges pinned by an open failure, newest first, from the rows loaded and the pins the head left out", () => {
    const loaded = [row(0), pinned(2), row(3), pinned(5)], older = pinned(40);

    const pins = pinsOf(loaded, [older, pinned(2)], 8);

    expect(pins.shown.map((r) => r.key)).toEqual(["m2", "m5", "m40"]);
    expect(pins.below).toBe(0);
  });

  it("counts the failed runs of every pin, and shows no more pins than its cap, naming how many wait below", () => {
    const pins = pinsOf([pinned(1, ["a", "b"]), pinned(2), pinned(3), pinned(4)], [], 2);

    expect(pins.shown.map((r) => r.key)).toEqual(["m1", "m2"]);
    expect(pins.below).toBe(2);
    expect(pins.failed).toBe(5);
  });

  it("is empty once the snapshot resolves the failure", () => {
    const resolved = row(2, { pinned: false, fails: { "apply-on-merge": open({ runId: "r2", at: "t" }) } });

    expect(pinsOf([row(0), resolved], [], 8)).toEqual({ shown: [], all: [], below: 0, failed: 0 });
  });
});

describe("a merge the snapshot resolved", () => {
  it("stays out of the band although an older copy of it, later in the list, still carries the failure", () => {
    const fresh = row(2, { fails: { "apply-on-merge": open({ runId: "r2", at: "t" }) } });

    expect(pinsOf([fresh], [pinned(2)], 8).shown).toEqual([]);
  });
});

describe("the rows' viewport under the band", () => {
  const grid: Viewport & { gap: number } = { top: 100, view: 272, rh: 34, gap: 10 };

  it("starts below the pins and a gap, and loses that height", () => {
    expect(portOf(grid, 0)).toEqual({ top: 100, view: 272, rh: 34 });
    expect(portOf(grid, 2)).toEqual({ top: 178, view: 194, rh: 34 });
  });

  it("keeps the rows scrolling beneath it while the pins stay where they are", () => {
    const port = portOf(grid, 1), head = Array.from({ length: PAGE }, (_, i) => row(i + 10)), sc = take(newScroll(), head, port);

    const scrolled = { ...sc, y: 200, ty: 200 };

    expect(place(sc, port)[0].y).toBe(port.top + port.rh / 2);
    expect(place(scrolled, port)[0].y).toBeLessThan(port.top);
  });
});

describe("the rows scrolling past the band", () => {
  it("skips the merges the band shows, and keeps the same scroll while it shows the same ones", () => {
    const pins = pinsOf([pinned(2), pinned(5)], [], 1), sc = withPins(newScroll(), pins);

    expect([...sc.skip]).toEqual(["m2"]);
    expect(withPins(sc, pinsOf([pinned(2), pinned(5)], [], 1))).toBe(sc);
    expect([...withPins(sc, pinsOf([row(2)], [], 1)).skip]).toEqual([]);
  });
});
