import { describe, expect, it } from "vitest";
import { drawing } from "./draw";

/** The alpha of every string a label prints, read from the fill it was set down in. */
function alphas(lift: boolean) {
  const seen: number[] = [];
  const state: Record<string, unknown> = {};
  const cx = new Proxy(state, {
    get: (t, p: string) => (p in t ? t[p] : p === "fillText" ? () => seen.push(Number(String(t.fillStyle).match(/[\d.]+(?=\)$)/)?.[0])) : () => ({ width: 40 })),
    set: (t, p: string, v) => ((t[p] = v), true),
  }) as unknown as CanvasRenderingContext2D;
  drawing({ cx, K: 1, ZS: 1, clock: 0, scale: 100, hover: null }).sunLabel([{ text: "Done", size: 13, y: -8, sub: false }, { text: "21 · 16 today", size: 11, y: 8, sub: true }], 0, 0, false, lift);
  return seen;
}

describe("sunLabel", () => {
  it("firms a lifted name and count up to a hot one's weight, for text on a black hole's shadow", () => {
    const [name, count] = alphas(true), [plainName, plainCount] = alphas(false);
    expect(name).toBeGreaterThanOrEqual(0.95);
    expect(count).toBeGreaterThanOrEqual(0.85);
    expect(plainName).toBeLessThan(name);
    expect(plainCount).toBeLessThan(count);
  });
});
