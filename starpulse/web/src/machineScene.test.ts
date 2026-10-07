import { describe, expect, it } from "vitest";
import { build } from "./scene";
import { merge, Moves } from "./sky";
import { paging, reveal } from "./machinePaging";
import { revealGoal, windowOf } from "./machineScroll";
import { stripScale, tickAt, ticks } from "./machineStrip";
import type { FlowSnapshot, Machine, Snapshot } from "./types";

const NOW = 1_800_000_000;
const machine = (...ids: string[]): Machine => ({ states: ids.map((id, i) => ({ id, name: id, initial: !i, final: i === ids.length - 1 })), transitions: ids.slice(1).map((t, i) => ({ source: ids[i], target: t, event: t })) });
const board: Machine = { ...machine("ready", "in_progress", "done"), subflows: [{ state: "in_progress", flow: "in-progress", exits: {}, parent: "board", when: "" }], mainLine: ["ready", "in_progress", "done"] };
/** `n` machines entered from the In Progress machine, kid0 the newest. */
function sky(n: number, page?: { machines: string[]; more: boolean }) {
  const kids: FlowSnapshot[] = Array.from({ length: n }, (_, i) => ({ name: `kid${i}`, machine: machine("a", "b"), agents: [], ties: [], parent: "in-progress", depth: 1, chain: [], nested: [], last: NOW - 60 * i, stuck: null }));
  const snap: Snapshot = {
    graphs: ["board", "in-progress", ...kids.map((k) => k.name)], dags: [], settled: {}, error: null, now: NOW,
    flows: [{ name: "board", machine: board, agents: [] }, { name: "in-progress", machine: machine("working", "pr_opened", "merged"), agents: [], ties: [], parent: null, depth: 0, chain: [], nested: [], last: NOW, stuck: null }, ...kids],
    ...(page ? { machinePage: { open: "in-progress", ...page } } : {}),
  };
  return merge(snap);
}
const level = { kind: "state", id: "in_progress" } as const;
const laid = (S: ReturnType<typeof sky>, p = S.machinePage ? paging(S.machinePage, (n) => S.flows[n].last ?? 0) : null) => {
  const moves = new Moves();
  moves.observe(S, NOW);
  return build({ S, moves, W: 1600, H: 900, T: NOW, scale: 100, paging: p }, level).top!;
};
const names = (n: number) => Array.from({ length: n }, (_, i) => `kid${i}`);

describe("the machine ledger's lane under a page", () => {
  it("lays out only the machines loaded, with a footer counting the older ones and the lane's scroll", () => {
    const top = laid(sky(45, { machines: names(20), more: true }));
    expect(top.rows.map((r) => r.name)).toEqual(names(20));
    expect(top.total).toBe(45);
    expect(top.more).toBe(25);
    expect(top.foot).toBeGreaterThan(0);
    expect(top.content).toBeCloseTo(top.rows.reduce((a, r) => a + r.h, 0) + top.foot);
    expect(top.max).toBeCloseTo(top.content - (top.laneBottom - top.laneTop));
  });

  it("draws no footer and scrolls nothing for a few machines that fit", () => {
    const top = laid(sky(2, { machines: names(2), more: false }));
    expect(top.rows).toHaveLength(2);
    expect([top.more, top.foot, top.max]).toEqual([0, 0, 0]);
  });

  it("does not stretch the loaded rows to fill the lane while older machines remain", () => {
    const some = laid(sky(45, { machines: names(3), more: true })).rows[0].h, alone = laid(sky(3, { machines: names(3), more: false })).rows[0].h;
    expect(alone).toBeGreaterThan(some);
  });

  it("shows every machine when the snapshot sends no page", () => {
    expect(laid(sky(30)).rows).toHaveLength(30);
  });

  it("scrolls a tick's row into view when the tick is clicked, loading the older machines between if it is not yet loaded", () => {
    const S = sky(45, { machines: names(20), more: true }), last = (n: string) => S.flows[n].last ?? 0;
    const p = paging(S.machinePage!, last), first = laid(S, p);
    expect(first.rows.map((r) => r.name)).not.toContain("kid40");
    const scale = stripScale(first.metaX, first.x1, NOW), found = ticks([{ at: NOW - 60 * 40, machine: "kid40", row: "kid40", from: null, dag: null }], first.ranked, scale);
    const click = tickAt(found, found[0].x)!, top = laid(S, reveal(p, last(click.entry.row)));
    const i = top.rows.findIndex((r) => r.name === click.entry.row), view = { h: top.laneBottom - top.laneTop, fs: 1 };
    expect(i).toBeGreaterThan(19);
    expect(windowOf(top.rows, revealGoal(top.rows, i, view, top.max), view).inView).toContain(i);
  });
});
