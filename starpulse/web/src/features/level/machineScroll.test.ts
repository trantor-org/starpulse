import { describe, expect, it } from "vitest";
import { dragTo, inputGoal, laneContent, revealGoal, thumbOf, windowOf } from "./machineScroll";

const view = { h: 400, fs: 1 };
const rows = (n: number, h = 100) => Array.from({ length: n }, () => ({ h }));

describe("the machine ledger's scroll", () => {
  it("holds the rows and, when older machines remain, a footer, and scrolls only past the view", () => {
    expect(laneContent(rows(3), 0, view)).toEqual({ content: 300, max: 0 });
    expect(laneContent(rows(10), 34, view)).toEqual({ content: 1034, max: 634 });
  });

  it("moves by the wheel in pixels or lines, and stays inside the rows", () => {
    expect(inputGoal({ wheel: 120, lines: false }, 0, view, 600)).toBe(120);
    expect(inputGoal({ wheel: 3, lines: true }, 0, view, 600)).toBe(54);
    expect(inputGoal({ wheel: -500, lines: false }, 100, view, 600)).toBe(0);
    expect(inputGoal({ wheel: 5000, lines: false }, 100, view, 600)).toBe(600);
  });

  it("moves by a page of nine tenths of the view, a step of 60 at the text size, and to either end", () => {
    expect(inputGoal({ key: "PageDown" }, 0, view, 1000)).toBe(360);
    expect(inputGoal({ key: "PageUp" }, 500, view, 1000)).toBe(140);
    expect(inputGoal({ key: "ArrowDown" }, 0, { h: 400, fs: 1.5 }, 1000)).toBe(90);
    expect(inputGoal({ key: "ArrowUp" }, 200, view, 1000)).toBe(140);
    expect(inputGoal({ key: "Home" }, 700, view, 1000)).toBe(0);
    expect(inputGoal({ key: "0" }, 700, view, 1000)).toBe(0);
    expect(inputGoal({ key: "End" }, 0, view, 1000)).toBe(1000);
  });

  it("leaves a key it does not scroll by alone", () => {
    expect(inputGoal({ key: "a" }, 40, view, 1000)).toBeNull();
    expect(inputGoal({ key: "Escape" }, 40, view, 1000)).toBeNull();
  });

  it("sizes the thumb to the share of the content in view, never under 24 px, and walks it with the scroll", () => {
    expect(thumbOf(400, view, 0, 0)).toBeNull();
    const top = thumbOf(1000, view, 0, 600)!, end = thumbOf(1000, view, 600, 600)!;
    expect(top.th).toBeCloseTo((top.y1 - top.y0) * 0.4);
    expect(top.ty).toBe(top.y0);
    expect(end.ty + end.th).toBeCloseTo(end.y1);
    expect(thumbOf(100000, view, 0, 99600)!.th).toBe(24);
  });

  it("drags the thumb to the scroll its travel gives, from where the drag began", () => {
    const t = thumbOf(1000, view, 0, 600)!, run = t.y1 - t.y0 - t.th;
    expect(dragTo(t, 0, run / 2, 600)).toBeCloseTo(300);
    expect(dragTo(t, 450, run, 600)).toBe(600);
    expect(dragTo(t, 100, -run, 600)).toBe(0);
  });

  it("places the rows from the scroll and names the ones in view, a row partly in view among them", () => {
    const w = windowOf(rows(10), 150, view);
    expect(w.ys).toEqual([-150, -50, 50, 150, 250, 350, 450, 550, 650, 750]);
    expect(w.inView).toEqual([1, 2, 3, 4, 5]);
    expect(windowOf(rows(10), 0, view).inView).toEqual([0, 1, 2, 3]);
  });

  it("scrolls a row to the middle of the view", () => {
    expect(revealGoal(rows(10), 5, view, 600)).toBe(350);
    expect(revealGoal(rows(10), 0, view, 600)).toBe(0);
    expect(revealGoal(rows(10), 9, view, 600)).toBe(600);
  });
});
