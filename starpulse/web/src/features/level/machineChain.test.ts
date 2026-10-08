import { describe, expect, it } from "vitest";
import { nestsOf, type Nest } from "./machineChain";
import { laneRows, rowLabels, type LaneMachine } from "./machineLanes";
import type { FlowSnapshot } from "../../api";

const states = (...ids: string[]) => ids.map((id, i) => ({ id, name: id, initial: !i, final: i === ids.length - 1 }));
const tr = (...ids: string[]) => ids.slice(1).map((t, i) => ({ source: ids[i], target: t, event: t }));
const line = (name: string, ...ids: string[]): LaneMachine => ({ name, states: states(...ids), transitions: tr(...ids), tasks: {} });
/** A machine whose first state fans into three branches that rejoin at the last. */
const fork = (name: string): LaneMachine => ({
  name, states: states("start", "a", "b", "c", "end"), tasks: {},
  transitions: ["a", "b", "c"].flatMap((m) => [{ source: "start", target: m, event: m }, { source: m, target: "end", event: "end" }]),
});
const nest = (name: string, kids: { state: string; nest: Nest }[] = [], st = ["s0", "s1", "s2"]): Nest => ({ name, states: st, kids });
/** A chain of `n` machines, each entered from the first state of the one above. */
const deep = (name: string, n: number): Nest => (n <= 1 ? nest(name) : nest(name, [{ state: "s0", nest: deep(`${name}-${n - 1}`, n - 1) }]));
const span = { x0: 300, x1: 1100 };
const measure = (t: string, px: number) => t.length * px * 0.55;
const rowOf = (m: LaneMachine, x = span, scale = 100) => laneRows([m], x, { scale, laneH: 10, measure }).rows[0];
type Seg = { x0: number; y0: number; x1: number; y1: number };
const segs = (pts: { x: number; y: number }[]): Seg[] => pts.slice(1).map((p, i) => ({ x0: pts[i].x, y0: pts[i].y, x1: p.x, y1: p.y }));
/** Two axis-aligned segments meet. */
const meet = (a: Seg, b: Seg) => Math.min(a.x0, a.x1) <= Math.max(b.x0, b.x1) && Math.min(b.x0, b.x1) <= Math.max(a.x0, a.x1) && Math.min(a.y0, a.y1) <= Math.max(b.y0, b.y1) && Math.min(b.y0, b.y1) <= Math.max(a.y0, a.y1);

describe("the band under a row that shows where its nesting is", () => {
  it("adds nothing to a row with no machine entered from it", () => {
    const r = rowOf(line("l", "a", "b", "c"));
    expect(r.band).toBe(0);
    expect(r.chain).toBeNull();
    expect(r.h).toBe(laneRows([line("l", "a", "b", "c")], span, { scale: 100, laneH: 10 }).rows[0].h);
  });

  it("grows a row by a band holding the nested machine's block under the column of the state it is entered from", () => {
    const plain = rowOf(line("l", "a", "b", "c")), r = rowOf({ ...line("l", "a", "b", "c"), nested: [{ state: "b", nest: nest("kid") }] });
    expect(r.band).toBeGreaterThan(20);
    expect(r.h).toBeCloseTo(plain.h + r.band);
    expect(r.c).toBeCloseTo(plain.c);
    const b = r.nodes.find((n) => n.id === "b")!, [col] = r.chain!.cols, [blk] = col.blocks;
    expect(blk.name).toBe("kid");
    expect(blk.lines).toHaveLength(1);
    expect(blk.lines[0].x).toBeCloseTo(b.x);
    expect(blk.lines[0].y).toBeGreaterThan(r.h - r.band);
    expect(blk.label.y).toBeLessThan(r.h);
  });

  it("runs a solid stem out of the state's left, down and along to its block, even for a lone state", () => {
    const r = rowOf({ ...line("l", "a", "b", "c"), nested: [{ state: "b", nest: nest("kid") }] }), b = r.nodes.find((n) => n.id === "b")!;
    const [stem] = r.chain!.cols[0].stems, [p0, p1, p2] = stem.pts;
    expect(stem.state).toBe("b");
    expect(p0.x).toBeLessThan(b.x - b.orbit);
    expect(p0.y).toBeCloseTo(r.c + b.oy);
    expect(p1.x).toBeLessThan(p0.x);
    expect(p2.y).toBeGreaterThan(r.h - r.band);
    expect(stem.drops[0].x).toBeCloseTo(r.chain!.cols[0].blocks[0].lines[0].x);
  });

  it("draws a deeper machine on its own line hung from the state it is entered from, four lines at most, then counts the rest", () => {
    const two = rowOf({ ...line("l", "a", "b"), nested: [{ state: "a", nest: nest("kid", [{ state: "s1", nest: nest("grand") }]) }] }).chain!.cols[0].blocks[0];
    expect(two.lines.map((l) => l.machine)).toEqual(["kid", "grand"]);
    expect(two.hangs).toHaveLength(1);
    expect(two.lines[1].x).toBeCloseTo(two.lines[0].x + two.lines[0].dx);
    expect(two.lines[1].y).toBeGreaterThan(two.lines[0].y);
    expect(two.tail).toBe("");
    const six = rowOf({ ...line("l", "a", "b"), nested: [{ state: "a", nest: deep("kid", 6) }] }).chain!.cols[0].blocks[0];
    expect(six.lines).toHaveLength(4);
    expect(six.tail).toBe(" +2 deeper");
  });

  it("grows the band with the deepest block, not with how many machines sit side by side", () => {
    const one = rowOf({ ...fork("f"), nested: [{ state: "a", nest: nest("k1") }] }).band;
    const deeper = rowOf({ ...fork("f"), nested: [{ state: "a", nest: deep("k1", 3) }] }).band;
    const wider = rowOf({ ...fork("f"), nested: [{ state: "a", nest: nest("k1") }, { state: "a", nest: nest("k2") }] }).band;
    expect(deeper).toBeGreaterThan(one);
    expect(wider).toBe(one);
  });

  it("sets the blocks of a column side by side, top state's first, each state running its own stem and none crossing another", () => {
    const r = rowOf({ ...fork("f"), nested: [{ state: "c", nest: nest("from-c") }, { state: "a", nest: nest("from-a") }, { state: "b", nest: nest("from-b") }, { state: "b", nest: nest("from-b2") }] });
    const [col] = r.chain!.cols, top = (id: string) => r.c + r.nodes.find((n) => n.id === id)!.oy;
    const order = ["a", "b", "c"].sort((p, q) => top(p) - top(q));
    expect(col.stems.map((s) => s.state)).toEqual(order);
    const xs = col.blocks.map((b) => b.lines[0].x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    expect(col.blocks.map((b) => b.name)[0]).toBe(`from-${order[0]}`);
    const lines = col.stems.map((s) => [...segs(s.pts), ...s.drops.map((d) => ({ x0: d.x, y0: d.y0, x1: d.x, y1: d.y1 }))]);
    for (const [i, a] of lines.entries()) for (const b of lines.slice(i + 1)) for (const p of a) for (const q of b) expect(meet(p, q)).toBe(false);
  });

  it("puts names that would not fit their block on two alternating baselines, and keeps one baseline when they fit", () => {
    const kids = ["a-rather-long-machine-name", "another-long-machine-name", "a-third-long-machine-name"].map((n) => ({ state: "b", nest: nest(n) }));
    const wide = rowOf({ ...line("l", "a", "b", "c"), nested: kids.slice(0, 2).map((k, i) => ({ ...k, nest: nest(`k${i}`) })) }).chain!.cols[0].blocks;
    expect(new Set(wide.map((b) => b.label.y)).size).toBe(1);
    const narrow = rowOf({ ...line("l", "a", "b", "c"), nested: kids }, { x0: 300, x1: 700 }).chain!.cols[0].blocks;
    const ys = narrow.map((b) => b.label.y);
    expect(ys[0]).toBe(ys[2]);
    expect(ys[1]).toBeGreaterThan(ys[0]);
  });

  it("keeps a row's state names off the stems and the band", () => {
    const r = rowOf({ ...fork("f"), nested: [{ state: "a", nest: nest("k1") }, { state: "b", nest: nest("k2") }, { state: "c", nest: nest("k3") }] });
    for (const l of rowLabels(r, { scale: 100, measure, ...span }, []))
      for (const k of r.chain!.keep) expect(l.x - 6 < k.x1 && k.x0 < l.x + l.w + 6 && l.y < k.y1 && k.y0 < l.y + l.h).toBe(false);
  });
});

describe("the machines entered from a row's machine", () => {
  const flow = (name: string, parent: string | null, from: string | null, ids = ["s0", "s1"]): FlowSnapshot =>
    ({ name, parent, ties: from ? [{ kind: "declared", machine: parent, state: from, count: null, dag: null, when: "" }] : [], machine: { states: states(...ids), transitions: tr(...ids) } }) as unknown as FlowSnapshot;
  const flows = Object.fromEntries([flow("top", null, null), flow("row", "top", "s0"), flow("kid", "row", "s1", ["x", "y", "z"]), flow("grand", "kid", "y"), flow("dag-only", "row", null)].map((f) => [f.name, f]));

  it("lists each machine entered from it with the state it is entered from, its states along its machine, and its own nested machines", () => {
    expect(nestsOf(flows, "row")).toEqual([{ state: "s1", nest: { name: "kid", states: ["x", "y", "z"], kids: [{ state: "y", nest: { name: "grand", states: ["s0", "s1"], kids: [] } }] } }]);
  });

  it("lists nothing for a machine with none entered from it", () => {
    expect(nestsOf(flows, "grand")).toEqual([]);
  });
});
