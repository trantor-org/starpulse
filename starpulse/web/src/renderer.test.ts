import { describe, expect, it } from "vitest";
import { arrivalRings, dagRings, tierColor } from "./renderer";
import { PULSE } from "./sky";

const FIN = 100;
const sweep = (fins: number[], from = FIN - 1, to = FIN + 12, step = 0.05) =>
  Array.from({ length: Math.round((to - from) / step) + 1 }, (_, i) => {
    const now = from + i * step;
    return { now, rings: fins.flatMap((f) => dagRings(f, now)) };
  });

describe("a DAG event's pulse", () => {
  it("is one ring that grows once and then stays gone", () => {
    const frames = sweep([FIN]), shown = frames.filter((f) => f.rings.length);
    expect(frames.every((f) => f.rings.length <= 1)).toBe(true);
    // one contiguous window: no ring before the run ends, none once it has faded
    expect(shown.length).toBeGreaterThan(0);
    expect(shown[0].now).toBeGreaterThanOrEqual(FIN);
    expect(shown[shown.length - 1].now).toBeLessThanOrEqual(FIN + PULSE + 0.05);
    expect(frames.slice(frames.indexOf(shown[shown.length - 1]) + 1).every((f) => f.rings.length === 0)).toBe(true);
    // the ring only ever grows: a restart from zero would be a second pulse
    const ages = shown.map((f) => f.rings[0]);
    expect(ages.every((a, i) => i === 0 || a > ages[i - 1])).toBe(true);
  });

  it("schedules one ring for each event, so two runs ending together ring twice", () => {
    const both = sweep([FIN, FIN]).filter((f) => f.rings.length);
    expect(Math.max(...both.map((f) => f.rings.length))).toBe(2);
    expect(Math.max(...sweep([FIN]).map((f) => f.rings.length))).toBe(1);
  });

  it("draws nothing for a DAG that has not run", () => {
    expect(dagRings(undefined, FIN)).toEqual([]);
  });
});

describe("a task's arrival pulse", () => {
  it("is one ring at any age, never a second one a beat behind", () => {
    const ages = Array.from({ length: 101 }, (_, i) => i / 100), rings = ages.map(arrivalRings);
    expect(rings.every((r) => r.length <= 1)).toBe(true);
    expect(rings[50]).toEqual([0.5]);
    expect([rings[0], rings[100]]).toEqual([[], []]);
  });
});

describe("an agent's colour", () => {
  it("follows the tier its profile names, whatever the effort", () => {
    expect(["@agent-deep-high", "@agent-deep-medium"].map(tierColor)).toEqual(["#c4b5fd", "#c4b5fd"]);
    expect(["@agent-standard-high", "@agent-standard-medium"].map(tierColor)).toEqual(["#67e8f9", "#67e8f9"]);
  });

  it("is the other colour for fast, a person or no assignee", () => {
    expect(["@agent-fast", "adin", ""].map(tierColor)).toEqual(["#fde68a", "#fde68a", "#fde68a"]);
    expect(tierColor()).toBe("#fde68a");
  });
});
