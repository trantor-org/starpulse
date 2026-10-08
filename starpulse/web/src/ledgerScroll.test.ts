import { describe, expect, it } from "vitest";
import {
  PAGE, begin, chip, dragMove, dragStart, ease, fail, footer, keyScroll, newScroll, place, receive, scrollToKey, take, thumbOf, wantsPage, wheelScroll, type Scroll, type Viewport,
} from "./ledgerScroll";
import type { LedgerRow } from "./types";

const row = (n: number, at = 100_000 - n * 60): LedgerRow => ({ key: `m${n}`, at, tasks: [`T-${n}`], runs: {}, fails: {}, pinned: false });
const rows = (from: number, count: number) => Array.from({ length: count }, (_, i) => row(from + i));
/** A viewport of 8 rows under a bus 100 units down. */
const vp: Viewport = { top: 100, view: 272, rh: 34 };
const opened = (head = rows(0, PAGE)): Scroll => take(newScroll(), head, vp);
const at = (sc: Scroll, y: number): Scroll => ({ ...sc, y, ty: y });
const keys = (sc: Scroll) => place(sc, vp).map((p) => p.row.key);

describe("scrolling the rows", () => {
  const sc = opened();
  const max = (PAGE + 1) * vp.rh - vp.view;

  it("clamps the wheel to the first row and to the footer, in pixels, lines and pages", () => {
    expect(wheelScroll(sc, vp, { deltaY: -500, deltaMode: 0 }, 1).ty).toBe(0);
    expect(wheelScroll(sc, vp, { deltaY: 100, deltaMode: 0 }, 2).ty).toBe(50);
    expect(wheelScroll(sc, vp, { deltaY: 3, deltaMode: 1 }, 1).ty).toBe(vp.rh);
    expect(wheelScroll(sc, vp, { deltaY: 1, deltaMode: 2 }, 1).ty).toBe(vp.view);
    expect(wheelScroll(sc, vp, { deltaY: 1e6, deltaMode: 0 }, 1).ty).toBe(max);
  });

  it("moves by a page, a row, or to either end by key, and leaves other keys alone", () => {
    const big = opened(rows(0, 60)), bigMax = 61 * vp.rh - vp.view, from = at(big, 500);
    expect(keyScroll(from, vp, "PageDown")?.ty).toBeCloseTo(500 + vp.view * 0.9);
    expect(keyScroll(from, vp, "PageUp")?.ty).toBeCloseTo(500 - vp.view * 0.9);
    expect(keyScroll(from, vp, "ArrowDown")?.ty).toBe(500 + vp.rh);
    expect(keyScroll(from, vp, "ArrowUp")?.ty).toBe(500 - vp.rh);
    expect(keyScroll(from, vp, "End")?.ty).toBe(bigMax);
    expect(keyScroll(from, vp, "Home")?.ty).toBe(0);
    expect(keyScroll(at(big, 10), vp, "PageUp")?.ty).toBe(0);
    expect(keyScroll(at(big, bigMax - 5), vp, "PageDown")?.ty).toBe(bigMax);
    expect(keyScroll(from, vp, "a")).toBeNull();
  });

  it("drags the thumb along its track, clamped at both ends, a zoomed canvas moving it k screen pixels per world unit", () => {
    const t = thumbOf(sc, vp, 24)!;
    expect(t.h).toBeCloseTo((vp.view * vp.view) / (vp.view + max));
    expect(t.y).toBe(0);
    const grabbed = dragStart(sc, 500);
    expect(dragMove(grabbed, vp, 500 + t.track / 2, 1, 24).ty).toBeCloseTo(max / 2);
    expect(dragMove(grabbed, vp, 500 + t.track, 1, 24).ty).toBeCloseTo(max);
    expect(dragMove(grabbed, vp, 500 + 9999, 1, 24).ty).toBe(max);
    expect(dragMove(grabbed, vp, 500 - 9999, 1, 24).ty).toBe(0);
    expect(dragMove(grabbed, vp, 500 + t.track, 2, 24).ty).toBeCloseTo(max / 2);
    expect(dragMove(grabbed, vp, 500 + t.track * 2, 2, 24).ty).toBeCloseTo(max);
  });

  it("has no thumb when every row fits", () => {
    expect(thumbOf(take(newScroll(), rows(0, 3), vp), vp, 24)).toBeNull();
  });

  it("eases the drawn offset to its target and stops on it", () => {
    let s = { ...sc, ty: 200 };
    for (let i = 0; i < 4; i++) s = ease(s, 0.05);
    expect(s.y).toBeGreaterThan(0);
    expect(s.y).toBeLessThan(200);
    for (let i = 0; i < 60; i++) s = ease(s, 0.05);
    expect(s.y).toBe(200);
  });
});

describe("drawing only the rows in view", () => {
  it("places the rows that cross the viewport, plus one beyond each edge for the clip, out of many", () => {
    const sc = at(opened(rows(0, 500)), 34 * 100 + 10);
    const placed = place(sc, vp);
    expect(placed.length).toBeLessThanOrEqual(Math.ceil(vp.view / vp.rh) + 3);
    expect(placed.map((p) => p.i)).toEqual(placed.map((_, k) => placed[0].i + k));
    expect(placed[0].i).toBe(99);
    for (const p of placed) expect(p.y + vp.rh / 2).toBeGreaterThan(vp.top - vp.rh);
    for (const p of placed) expect(p.y - vp.rh / 2).toBeLessThan(vp.top + vp.view + vp.rh);
    expect(placed.some((p) => p.y > vp.top && p.y < vp.top + vp.view)).toBe(true);
  });

  it("lays row i one row height under row i-1, newest at the top of the viewport", () => {
    const [a, b] = place(opened(), vp);
    expect([a.row.key, a.y, b.y - a.y]).toEqual(["m0", vp.top + vp.rh / 2, vp.rh]);
  });

  it("holds a few rows still and draws no more than it has", () => {
    expect(keys(opened(rows(0, 3)))).toEqual(["m0", "m1", "m2"]);
  });
});

describe("loading older merges", () => {
  const end = (s: Scroll) => at(s, (s.rows.length + 1) * vp.rh - vp.view);

  it("asks for the next page once when the footer comes into view, then again for each page that ends in view", () => {
    let s = opened();
    expect(wantsPage(s, vp, 0)).toBe(false);
    s = end(s);
    expect(wantsPage(s, vp, 0)).toBe(true);
    s = begin(s);
    expect([wantsPage(s, vp, 0), wantsPage(s, vp, 99)]).toEqual([false, false]);
    s = receive(s, rows(PAGE, PAGE), true);
    expect(s.rows).toHaveLength(2 * PAGE);
    expect(wantsPage(s, vp, 0)).toBe(false);
    expect(wantsPage(end(s), vp, 0)).toBe(true);
    s = receive(begin(end(s)), rows(2 * PAGE, 5), false);
    expect(s.rows).toHaveLength(2 * PAGE + 5);
    expect(wantsPage(end(s), vp, 0)).toBe(false);
  });

  it("fetches at once while more remain and the rows do not fill the viewport", () => {
    const s = { ...opened(rows(0, 5)), more: true };
    expect([wantsPage(s, vp, 0), wantsPage({ ...s, more: false }, vp, 0)]).toEqual([true, false]);
  });

  it("assumes more only while the head holds a whole page", () => {
    expect([opened().more, opened(rows(0, PAGE - 1)).more]).toEqual([true, false]);
  });

  it("retries a failed page after a pause, not on every frame", () => {
    const s = fail(begin(end(opened())), 100);
    expect([wantsPage(s, vp, 101), wantsPage(s, vp, 106)]).toEqual([false, true]);
  });

  it("keeps a row once, whichever way it arrives, and in order", () => {
    const s = receive(opened(), [...rows(PAGE - 2, 4)], true);
    expect(s.rows.map((r) => r.key)).toEqual(Array.from({ length: PAGE + 2 }, (_, i) => `m${i}`));
  });

  it("shows the loading row under the loaded ones while more remain, and the oldest-merge row once none do", () => {
    const s = opened();
    const down = end(s), y = vp.top + PAGE * vp.rh - down.y + vp.rh / 2;
    expect(footer(down, vp)).toEqual({ y, end: false, rows: PAGE });
    expect(footer({ ...down, more: false }, vp)?.end).toBe(true);
    expect(footer(s, vp)).toBeNull();
  });
});

describe("a merge arriving", () => {
  const scrolled = () => at(opened(), 200);

  it("keeps the rows in view where they are when the reader is scrolled down, and counts it on the chip", () => {
    const before = scrolled(), viewed = place(before, vp).map((p) => [p.row.key, p.y]);
    const after = take(before, [row(-1, 100_100), ...rows(0, PAGE - 1)], vp);
    expect(place(after, vp).map((p) => [p.row.key, p.y])).toEqual(viewed);
    expect(after.rows).toHaveLength(PAGE + 1);
    expect(after.fresh).toBe(1);
    expect(chip(after, vp)).toBe("↑ 1 new merge");
  });

  it("counts each one while the reader stays down", () => {
    let s = take(scrolled(), [row(-1, 100_100), ...rows(0, PAGE - 1)], vp);
    s = take(s, [row(-2, 100_200), row(-1, 100_100), ...rows(0, PAGE - 2)], vp);
    expect([s.fresh, chip(s, vp)]).toEqual([2, "↑ 2 new merges"]);
  });

  it("reads back to newest when scrolled with nothing new, and says nothing at the top", () => {
    expect([chip(scrolled(), vp), chip(opened(), vp)]).toEqual(["↑ back to newest", null]);
  });

  it("lets a reader at the top see the new row at the top, with nothing to count", () => {
    const s = take(at(opened(), 3), [row(-1, 100_100), ...rows(0, PAGE - 1)], vp);
    expect([s.y, s.fresh, place(s, vp)[0].row.key]).toEqual([3, 0, "m-1"]);
  });

  it("clears the count once the reader is back at the newest row", () => {
    const s = take(scrolled(), [row(-1, 100_100), ...rows(0, PAGE - 1)], vp);
    expect(keyScroll(s, vp, "Home")!.fresh).toBe(0);
  });

  it("keeps the older rows a reader loaded when the head moves on, and takes the head's newer copy of a row", () => {
    const loaded = receive(opened(), rows(PAGE, PAGE), false);
    const moved = { ...row(0), tasks: ["T-0 again"] };
    const s = take(at(loaded, 300), [row(-1, 100_100), moved, ...rows(1, PAGE - 2)], vp);
    expect(s.rows).toHaveLength(2 * PAGE + 1);
    expect(s.rows.find((r) => r.key === "m0")?.tasks).toEqual(["T-0 again"]);
    expect(s.rows.at(-1)!.key).toBe(`m${2 * PAGE - 1}`);
  });
});

describe("scrolling to a merge", () => {
  it("scrolls it to the middle of the view, and not at all when it is already in view", () => {
    const s = opened(rows(0, 60));
    expect(scrollToKey(s, vp, "m30")!.ty).toBe(30 * vp.rh - vp.view / 2 + vp.rh / 2);
    expect(scrollToKey(s, vp, "m2")).toEqual(s);
    expect(scrollToKey(s, vp, "nope")).toEqual(s);
  });
});

describe("rows drawn elsewhere", () => {
  const pinned = (sc: Scroll, ...keys: string[]): Scroll => ({ ...sc, skip: new Set(keys) });

  it("leave the list: the rows below them move up, the extent shrinks and the footer follows the last row left", () => {
    const sc = pinned(opened(rows(0, 6)), "m1", "m2");

    expect(place(sc, vp).map((p) => p.row.key)).toEqual(["m0", "m3", "m4", "m5"]);
    expect(place(sc, vp)[1].y).toBe(vp.top + vp.rh / 2 + vp.rh);
    expect(footer(sc, vp)!.y).toBe(vp.top + 4 * vp.rh + vp.rh / 2);
    expect(footer(sc, vp)!.rows).toBe(4);
  });

  it("do not count toward the length the thumb and the keys run through", () => {
    const plain = opened(rows(0, PAGE)), skipped = pinned(plain, "m0", "m1", "m2");

    expect(keyScroll(skipped, vp, "End")!.ty).toBe((PAGE - 3 + 1) * vp.rh - vp.view);
    expect(keyScroll(plain, vp, "End")!.ty).toBe((PAGE + 1) * vp.rh - vp.view);
  });

  it("do not make the footer ask for a page before the last row left is in view", () => {
    const sc = { ...pinned(opened(rows(0, PAGE)), "m0"), more: true };

    expect(wantsPage(at(sc, (PAGE - 1) * vp.rh - vp.view), vp, 0)).toBe(false);
    expect(wantsPage(at(sc, (PAGE - 1) * vp.rh - vp.view + vp.rh), vp, 0)).toBe(true);
  });
});
