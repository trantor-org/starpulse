import { describe, expect, it } from "vitest";
import { entryAt, entryPath, laneRows, rowLabels, type LaneMachine } from "./machineLanes";

const states = (...ids: string[]) => ids.map((id, i) => ({ id, name: id, initial: !i, final: i === ids.length - 1 }));
const line = (name: string, ...ids: string[]): LaneMachine => ({ name, states: states(...ids), transitions: ids.slice(1).map((t, i) => ({ source: ids[i], target: t, event: t })), tasks: {} });
/** A machine whose first state fans into `n` branches that all rejoin at the last. */
const fan = (name: string, n: number): LaneMachine => {
  const mid = Array.from({ length: n }, (_, i) => `m${i}`);
  return { name, states: states("start", ...mid, "end"), transitions: [...mid.map((m) => ({ source: "start", target: m, event: m })), ...mid.map((m) => ({ source: m, target: "end", event: "end" }))], tasks: {} };
};
const span = { x0: 300, x1: 1100 };
const frame = (laneH: number, scale = 100) => ({ scale, laneH });

describe("the machine ledger's lane", () => {
  it("makes a row as tall as its meta column or its machine, whichever is taller", () => {
    const [flat, wide] = laneRows([line("flat", "a", "b", "c"), fan("wide", 5)], span, frame(10)).rows;
    expect(flat.h).toBeGreaterThan(60);
    expect(wide.h).toBeGreaterThan(flat.h);
    expect(laneRows([fan("wide", 5)], span, frame(10)).rows[0].h).toBe(wide.h);
  });

  it("stretches a few rows to fill the lane, never past 3.2 times their height", () => {
    const flat = laneRows([line("a", "x", "y")], span, frame(10)).rows[0].h;
    const some = laneRows([line("a", "x", "y"), line("b", "x", "y")], span, frame(3 * flat)), most = laneRows([line("a", "x", "y"), line("b", "x", "y")], span, frame(100 * flat));
    expect(some.k).toBeGreaterThan(1);
    expect(some.rows.reduce((a, r) => a + r.h, 0)).toBeLessThanOrEqual(3 * flat);
    expect(most.k).toBe(3.2);
    expect(most.rows[0].h).toBeCloseTo(3.2 * flat);
  });

  it("leaves rows at their own height when there are more than a page of them", () => {
    const many = Array.from({ length: 21 }, (_, i) => line(`m${i}`, "a", "b"));
    const { rows, k } = laneRows(many, span, frame(100000));
    expect(rows).toHaveLength(21);
    expect(k).toBe(1);
  });

  it("stacks the rows from the top of the lane in the order given, each starting where the one above ends", () => {
    const { rows } = laneRows([line("a", "x", "y"), fan("b", 3), line("c", "x", "y")], span, frame(10));
    expect(rows.map((r) => r.name)).toEqual(["a", "b", "c"]);
    expect(rows.map((r) => r.y)).toEqual([0, rows[0].h, rows[0].h + rows[1].h]);
  });

  it("spreads a row's states across the lane by depth and its branches above and below the main line", () => {
    const [r] = laneRows([fan("f", 3)], span, frame(10)).rows, at = (id: string) => r.nodes.find((n) => n.id === id)!;
    expect(at("start").x).toBeCloseTo(span.x0);
    expect(at("end").x).toBeCloseTo(span.x1);
    expect(at("m0").x).toBeGreaterThan(at("start").x);
    expect(at("m0").x).toBe(at("m1").x);
    expect(at("m0").oy).toBe(0);
    expect(at("m1").oy).toBeLessThan(0);
    expect(at("m2").oy).toBeGreaterThan(0);
    expect(r.c + at("start").oy).toBeGreaterThan(0);
    expect(r.c + Math.max(...r.nodes.map((n) => n.oy))).toBeLessThan(r.h);
  });
});

describe("a row's state names", () => {
  const measure = (t: string, px: number) => t.length * px * 0.55;
  const labelsOf = (m: LaneMachine, x = span, laneH = 10) => {
    const { rows } = laneRows([m], x, frame(laneH));
    return { row: rows[0], labels: rowLabels(rows[0], { scale: 100, measure, ...x }, []) };
  };
  const box = (l: { x: number; y: number; w: number; h: number }) => ({ x0: l.x, x1: l.x + l.w, y0: l.y, y1: l.y + l.h });

  it("alternates below and above the line along a machine, each inside its row", () => {
    const { row, labels } = labelsOf(line("l", "aa", "bb", "cc", "dd"));
    expect(labels.map((l) => l.id)).toEqual(["aa", "bb", "cc", "dd"]);
    const at = (id: string) => labels.find((l) => l.id === id)!;
    expect(at("aa").y).toBeGreaterThan(row.c);
    expect(at("bb").y + at("bb").h).toBeLessThan(row.c);
    expect(at("cc").y).toBeGreaterThan(row.c);
    for (const l of labels) {
      expect(l.y).toBeGreaterThanOrEqual(1);
      expect(l.y + l.h).toBeLessThanOrEqual(row.h - 1);
    }
  });

  it("names a state beside it in a column of three or more, which holds the places above and below", () => {
    const { row, labels } = labelsOf(fan("f", 3));
    const node = row.nodes.find((n) => n.id === "m1")!, label = labels.find((l) => l.id === "m1")!;
    expect(label.x).toBeGreaterThan(node.x);
    expect(label.y + label.h / 2).toBeCloseTo(row.c + node.oy);
  });

  it("drops a name that would touch another rather than overprint it", () => {
    const { labels } = labelsOf(line("l", "a-long-name", "another-long-name", "yet-another-name", "the-last-name"), { x0: 300, x1: 420 });
    expect(labels.length).toBeGreaterThan(0);
    expect(labels.length).toBeLessThan(4);
    const boxes = labels.map(box);
    for (const [i, a] of boxes.entries()) for (const b of boxes.slice(i + 1)) expect(a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1).toBe(false);
  });

  it("keeps clear of what it is given, such as a DAG star at the row's head", () => {
    const { row } = labelsOf(line("l", "aa", "bb"));
    const first = row.nodes[0], clear = rowLabels(row, { scale: 100, measure, ...span }, []), blocked = rowLabels(row, { scale: 100, measure, ...span }, [{ x: first.x, y: row.c + 18, r: 40 }]);
    expect(clear.some((l) => l.id === "aa")).toBe(true);
    expect(blocked.some((l) => l.id === "aa" && Math.hypot(l.x + l.w / 2 - first.x, l.y - row.c - 18) < 40)).toBe(false);
  });
});

describe("the path a session takes into a row", () => {
  const from = { x: 500, y: 100 }, to = { x: 300, y: 400 };
  it("runs from the state it leaves to the row's first state", () => {
    const e = entryPath(from, to);
    expect(entryAt(e, 0)).toEqual(from);
    expect(entryAt(e, 1)).toEqual(to);
  });
  it("drops straight down from the state it leaves and arrives from above and from the left", () => {
    const e = entryPath(from, to);
    expect(e.c1.x).toBe(from.x);
    expect(e.c1.y).toBeGreaterThan(from.y);
    expect(e.c2.x).toBeLessThan(to.x);
    expect(e.c2.y).toBeLessThan(to.y);
  });
  it("arrives from below when the row is above the state", () => {
    const e = entryPath({ x: 500, y: 400 }, { x: 300, y: 100 });
    expect(e.c1.y).toBeLessThan(400);
    expect(e.c2.y).toBeGreaterThan(100);
  });
});
