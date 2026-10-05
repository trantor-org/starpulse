import { describe, expect, it } from "vitest";
import { GROW_MS, sizes } from "./grow";

/** The values `key` shows on 16 ms frames from `t0` to `t1`, its target set by `to(t)` on each frame. */
const frames = (s: ReturnType<typeof sizes>, to: (t: number) => number, t0: number, t1: number) => {
  const out: number[] = [];
  for (let t = t0; t <= t1; t += 16) out.push(s.of("done", to(t), t));
  return out;
};
const steps = (xs: number[]) => xs.slice(1).map((x, i) => x - xs[i]);

describe("a body's drawn size", () => {
  it("starts at its size, then moves to a new one without jumping and settles within GROW_MS", () => {
    const s = sizes();
    expect(s.of("done", 40, 0)).toBe(40);
    const xs = frames(s, () => 60, 1000, 1000 + GROW_MS);
    expect(xs[0]).toBe(40);
    expect(steps(xs).every((d) => d >= 0 && d < 2)).toBe(true);
    expect(xs[xs.length - 1]).toBeCloseTo(60, 0);
    expect(s.growing()).toBe(true);
    frames(s, () => 60, 1000 + GROW_MS + 16, 1000 + 3 * GROW_MS);
    expect(s.growing()).toBe(false);
  });
  it("takes most of a second, so a resize reads as a glide: a quarter second in, it has gone less than half the way", () => {
    const s = sizes();
    s.of("done", 40, 0);
    expect(frames(s, () => 60, 1000, 1256).pop()!).toBeLessThan(50);
  });
  it("keeps moving through a new target mid-move instead of stopping and starting again", () => {
    const s = sizes();
    s.of("done", 40, 0);
    // a busy Board: the size steps up 5 every 100 ms, as snapshots arrive faster than one ease lasts
    const xs = frames(s, (t) => 40 + 5 * Math.ceil(t / 100), 16, 1000);
    expect(Math.min(...steps(xs).slice(12))).toBeGreaterThan(0.2);
  });
  it("turns a change mid-move from the size it shows, so it never jumps", () => {
    const s = sizes();
    s.of("done", 40, 0);
    const mid = frames(s, () => 60, 1000, 1000 + GROW_MS / 2).pop()!;
    expect(s.of("done", 30, 1000 + GROW_MS / 2 - (GROW_MS / 2) % 16)).toBe(mid);
    expect(frames(s, () => 30, 1000 + GROW_MS, 1000 + 4 * GROW_MS).pop()).toBeCloseTo(30, 1);
  });
});
