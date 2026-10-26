import { describe, expect, it } from "vitest";
import { contrast, deltaE, hex, hueGap, lch, mixLch } from "./color";

describe("color", () => {
  it("round-trips a hex through OKLCH", () => {
    for (const h of ["#818cf8", "#1d1f21", "#f0c674", "#ffffff"]) expect(hex(lch(h))).toBe(h);
  });

  it("measures WCAG contrast from 1 to 21", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 1);
    expect(contrast("#777777", "#777777")).toBeCloseTo(1, 5);
  });

  it("measures OKLab distance, zero for the same color", () => {
    expect(deltaE("#818cf8", "#818cf8")).toBe(0);
    expect(deltaE("#000000", "#ffffff")).toBeCloseTo(1, 1);
  });

  it("mixes hue the short way round and takes the other hue for a grey", () => {
    expect(hueGap(350, 10)).toBe(20);
    const grey = lch("#808080");
    const red = lch("#ff0000");
    expect(mixLch(grey, red, 0.5)[2]).toBeCloseTo(red[2], 5);
  });
});
