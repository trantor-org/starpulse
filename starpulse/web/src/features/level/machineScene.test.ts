import { describe, expect, it } from "vitest";
import { build } from "../../render/scene";
import { merge, Moves } from "../../render/sky";
import type { FlowSnapshot, Machine, Snapshot } from "../../api";

const NOW = 1_800_000_000;
const machine = (...ids: string[]): Machine => ({ states: ids.map((id, i) => ({ id, name: id, initial: !i, final: i === ids.length - 1 })), transitions: ids.slice(1).map((t, i) => ({ source: ids[i], target: t, event: t })) });
const board: Machine = { ...machine("ready", "in_progress", "done"), submachines: [{ state: "in_progress", machine: "in-progress", exits: {}, parent: "board", when: "" }], mainLine: ["ready", "in_progress", "done"] };
/** `n` machines entered from the In Progress machine, kid0 the newest. */
function sky(n: number) {
  const kids: FlowSnapshot[] = Array.from({ length: n }, (_, i) => ({ name: `kid${i}`, machine: machine("a", "b"), agents: [], ties: [], parent: "in-progress", depth: 1, chain: [], nested: [], last: NOW - 60 * i, stuck: null }));
  const snap: Snapshot = {
    graphs: ["board", "in-progress", ...kids.map((k) => k.name)], dags: [], settled: {}, error: null, now: NOW,
    flows: [{ name: "board", machine: board, agents: [] }, { name: "in-progress", machine: machine("working", "pr_opened", "merged"), agents: [], ties: [], parent: null, depth: 0, chain: [], nested: [], last: NOW, stuck: null }, ...kids],
  };
  return merge(snap);
}
const level = { kind: "state", id: "in_progress" } as const;
const laid = (S: ReturnType<typeof sky>, only?: { task: string; machines: string[] }) => {
  const moves = new Moves();
  moves.observe(S, NOW);
  return build({ S, moves, W: 1600, H: 900, T: NOW, scale: 100, only }, level).top!;
};
const names = (n: number) => Array.from({ length: n }, (_, i) => `kid${i}`);

describe("the machine ledger's lane", () => {
  it("lays out every machine the snapshot holds, newest first, with the lane's scroll", () => {
    const top = laid(sky(45));
    expect(top.rows.map((r) => r.name)).toEqual(names(45));
    expect(top.total).toBe(45);
    expect(top.content).toBeCloseTo(top.rows.reduce((a, r) => a + r.h, 0));
    expect(top.max).toBeCloseTo(top.content - (top.laneBottom - top.laneTop));
  });

  it("scrolls nothing for a few machines that fit", () => {
    const top = laid(sky(2));
    expect(top.rows).toHaveLength(2);
    expect(top.max).toBe(0);
  });

  it("narrows the rows to the machines a pinned task has a session in", () => {
    const top = laid(sky(45), { task: "DEMO-7", machines: ["kid30", "kid3", "gone"] });
    expect(top.rows.map((r) => r.name)).toEqual(["kid3", "kid30"]);
    expect(top.ranked).toEqual(["kid3", "kid30"]);
    expect([top.total, top.task]).toEqual([2, "DEMO-7"]);
  });
});
