import { describe, expect, it } from "vitest";
import { padMachines } from "./demoMachines";
import { PAGE } from "./machineLanes";
import type { FlowSnapshot, Machine, Snapshot } from "./api";

const DAY = 86400;
const machine: Machine = {
  states: [{ id: "start", name: "Start", initial: true, final: false }, { id: "done", name: "Done", initial: false, final: true }],
  transitions: [{ source: "start", target: "done", event: "GO" }],
};
const kid = (name: string, last: number): FlowSnapshot => ({
  name, machine, parent: "top", depth: 1, chain: [], nested: [], ties: [], last, stuck: null,
  agents: [{ id: `${name}-a`, title: name, task: "T-1", state: "done", model: "", steps: 1, trail: [{ state: "done", event: "GO", at: last - 60 }], active: last }],
});
const snap = (): Snapshot => ({
  graphs: [], dags: [], settled: {}, error: null, now: 1_000_000,
  flows: [
    { name: "top", machine, agents: [], parent: null, depth: 0, chain: [], nested: ["a", "b"], ties: [], last: null, stuck: null },
    kid("a", 999_000), kid("b", 998_000),
  ],
  machinePage: { open: "top", machines: ["a", "b"], more: false },
  machineStrip: { entries: [] },
});

describe("padding a demo's machines", () => {
  it("brings the machines under the open one to the count, cloned from the ones it has, newest first by name", () => {
    const out = padMachines(snap(), 45), kids = out.flows.filter((f) => f.parent === "top");
    expect(kids).toHaveLength(45);
    expect(new Set(kids.map((f) => f.name)).size).toBe(45);
    expect(out.flows.find((f) => f.name === "top")!.nested).toHaveLength(45);
  });

  it("spreads their last moves over the 24 hours before now, the newest first", () => {
    const out = padMachines(snap(), 45), now = out.now, lasts = out.flows.filter((f) => f.parent === "top").map((f) => f.last!);
    expect(Math.max(...lasts)).toBeLessThanOrEqual(now);
    expect(Math.min(...lasts)).toBeGreaterThan(now - DAY);
    expect(Math.min(...lasts)).toBeLessThan(now - DAY / 2);
  });

  it("pages the first of them and says more remain, and leaves a count it already has alone", () => {
    const out = padMachines(snap(), 45);
    expect(out.machinePage).toEqual({ open: "top", machines: expect.any(Array), more: true });
    expect(out.machinePage!.machines).toHaveLength(PAGE);
    expect(padMachines(snap(), 2).machinePage).toEqual({ open: "top", machines: ["a", "b"], more: false });
  });

  it("draws one strip entry per session start inside the 24 hours, oldest first, each on its machine's row", () => {
    const out = padMachines(snap(), 45), entries = out.machineStrip!.entries;
    expect(entries.length).toBeGreaterThanOrEqual(45);
    expect(entries.every((e) => e.at > out.now - DAY && e.row === e.machine)).toBe(true);
    expect(entries.map((e) => e.at)).toEqual([...entries.map((e) => e.at)].sort((x, y) => x - y));
    expect(entries.some((e) => e.dag)).toBe(true);
    expect(new Set(entries.flatMap((e) => (e.from ? [e.from.state] : []))).size).toBeGreaterThan(1);
  });
});
