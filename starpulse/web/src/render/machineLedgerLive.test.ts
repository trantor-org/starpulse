import { describe, expect, it } from "vitest";
import capture from "./fixtures/events-snapshot.json";
import type { Snapshot } from "../api";
import { build } from "./scene";
import { merge, Moves } from "./sky";

// a drill-down of the captured live /api/events snapshot's phase flows
const snap = capture as unknown as Snapshot;
const drill = (flow: string, scale: number) => {
  const S = merge(snap), moves = new Moves();
  moves.observe(S, snap.now ?? 0);
  return build({ S, moves, W: 1920, H: 1080, T: snap.now ?? 0, scale }, { kind: "machine", flow }).top!;
};

describe.each(["build", "deliver"])("the live %s phase flow's drill-down", (flow) => {
  const tasks = snap.flows.find((f) => f.name === flow)!.agents.reduce<Record<string, number>>((a, t) => ({ ...a, [t.state]: (a[t.state] ?? 0) + 1 }), {});

  it.each([100, 125, 150])("counts each state's tasks and fills its columns up to xEnd at %i%%", (scale) => {
    const top = drill(flow, scale), xs = [...new Set(top.nodes.map((n) => n.x))].sort((a, b) => a - b);

    expect(Object.keys(tasks)).not.toHaveLength(0);
    for (const n of top.nodes) expect(n.n, n.id).toBe(tasks[n.id] ?? 0);
    expect(xs[0]).toBe(top.x0);
    expect(xs[xs.length - 1]).toBeCloseTo(top.xEnd, 5);
    expect(top.x1 - top.xEnd).toBeGreaterThan(0);
  });
});
