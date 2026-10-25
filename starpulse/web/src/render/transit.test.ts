import { describe, expect, it } from "vitest";
import capture from "./fixtures/events-snapshot.json";
import { merge, mergePhases } from "./sky";
import { CLEAR, placeBranches, STEP, wantsOf } from "./transit";
import type { Hub, Want } from "./transit";
import type { Curve, NameBox, Pt } from "./scene";
import type { Snapshot } from "../api";

const hub: Hub = { id: "in_progress", x: 400, y: 300, edge: 40 };
const want = (task: string, stations = 4, subs: Want["subs"] = []): Want => ({ task, sun: hub.id, stations, subs });
const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);
const along = ({ p0, c, p1 }: Curve, n = 60): Pt[] =>
  Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return { x: u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, y: u * u * p0.y + 2 * u * t * c.y + t * t * p1.y };
  });
const inBox = (p: Pt, b: NameBox, pad: number) => p.x > b.x0 - pad && p.x < b.x1 + pad && p.y > b.y0 - pad && p.y < b.y1 + pad;
const curve: Curve = { p0: { x: 400, y: 340 }, c: { x: 460, y: 420 }, p1: { x: 520, y: 380 } };
const name: NameBox = { of: "in_progress", x0: 360, y0: 230, x1: 440, y1: 250 };

describe("placeBranches", () => {
  it("keeps every station of one branch a station-step from every other branch's", () => {
    const branches = placeBranches([hub], ["TASK-1", "TASK-2", "TASK-3", "TASK-4"].map((t) => want(t, 5, [{ at: 2, stations: 2 }])));

    const stations = branches.map((b) => b.stations);
    const gaps = stations.flatMap((a, i) => stations.slice(i + 1).flatMap((b) => a.flatMap((p) => b.map((q) => dist(p, q)))));
    expect([branches.length, Math.min(...gaps) >= STEP]).toEqual([4, true]);
  });

  it("leaves a submachine's ray from its parent's station at 90 degrees to the parent's line", () => {
    const [b] = placeBranches([hub], [want("TASK-1", 5, [{ at: 2, stations: 3 }])]);

    const ray = b.rays[0];
    const [prev, here, next] = [b.stations[1], b.stations[2], b.stations[3]];
    const line = { x: next.x - prev.x, y: next.y - prev.y };
    const out = { x: ray.stations[0].x - here.x, y: ray.stations[0].y - here.y };
    const cos = (line.x * out.x + line.y * out.y) / (Math.hypot(line.x, line.y) * Math.hypot(out.x, out.y));
    expect(Math.abs(cos)).toBeLessThan(0.1);
  });

  it("clears the Board's curves and names, rays included", () => {
    const branches = placeBranches([hub], ["TASK-1", "TASK-2", "TASK-3"].map((t) => want(t, 5, [{ at: 1, stations: 2 }])), { curves: [curve], names: [name] });

    const stations = branches.flatMap((b) => [...b.stations, ...b.rays.flatMap((r) => r.stations)]);
    const onCurve = stations.filter((p) => along(curve).some((q) => dist(p, q) < CLEAR));
    const onName = stations.filter((p) => inBox(p, name, CLEAR));
    expect([stations.length > 0, onCurve, onName]).toEqual([true, [], []]);
  });

  it("removes a branch whose task is gone and keeps the others where they were", () => {
    const first = placeBranches([hub], [want("TASK-1"), want("TASK-2")]);

    const next = placeBranches([hub], [want("TASK-2")], { curves: [], names: [] }, first);
    expect(next.map((b) => [b.task, b.stations])).toEqual([["TASK-2", first[1].stations]]);
  });
});

describe("a live snapshot", () => {
  it("draws a branch off the Board state of every task-joined agent in a phase flow", () => {
    const sky = merge(capture as unknown as Snapshot);
    const hubs: Hub[] = sky.board.machine.states.map((s, i) => ({ id: s.id, x: 600 * (i % 4), y: 600 * Math.floor(i / 4), edge: 40 }));

    const wants = wantsOf(sky);
    const branches = placeBranches(hubs, wants);

    const joined = mergePhases(sky).filter((run) => sky.board.machine.submachines?.some((m) => m.state === run.sun && m.machine === run.flow));
    expect([joined.length > 0, branches.map((b) => [b.task, b.sun]).sort()]).toEqual([true, joined.map((r) => [r.task, r.sun]).sort()]);
  });
});
