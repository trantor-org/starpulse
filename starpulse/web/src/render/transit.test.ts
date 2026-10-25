import { beforeEach, describe, expect, it, vi } from "vitest";
import capture from "./fixtures/events-snapshot.json";
import type { Snapshot } from "../api";
import type { Galaxy, Pt, Scene } from "./scene";

// transit.ts keeps its branches and dots between frames, so each case loads it afresh
let T: typeof import("./transit"), sc: typeof import("./scene"), sky: typeof import("./sky");
beforeEach(async () => {
  vi.resetModules();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  [T, sc, sky] = await Promise.all([import("./transit"), import("./scene"), import("./sky")]);
});

/** The Board level the renderer lays out for `snap` at `scale`% text size, with its branches grown for `secs` seconds of frames. */
function board(snap: Snapshot, { scale = 100, secs = 3, from = 0, W = 1920 } = {}): Scene {
  const S = sky.merge(snap), moves = new sky.Moves();
  moves.observe(S, snap.now ?? 0);
  const scene = sc.build({ S, moves, W, H: 1080, T: snap.now ?? 0, scale }, { kind: "board" });
  run(scene, from, secs);
  return scene;
}
const run = (scene: Scene, from: number, secs: number) => {
  for (let t = from; t <= from + secs; t += 1 / 60) T.placeBranches(scene, t);
};
const live = () => structuredClone(capture) as unknown as Snapshot;
/** The preview's `?mock=1&extra=8&sim=3` at `scale`% on a `W`-wide canvas: phase tasks on build, deliver and review_fix, and the pair walked from Deliver into the
 *  CI it opens, which branches off Deliver's station. */
function mock(scale = 100, W = 1920): Scene {
  vi.stubGlobal("location", { search: "?mock=1&extra=8&sim=3" });
  const clock = vi.spyOn(performance, "now").mockReturnValue(0);
  board(live(), { scale, W });
  clock.mockReturnValue(60_000);
  return board(live(), { scale, W, from: 3, secs: 6 });
}
const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);
const stationsOf = (l: ReturnType<typeof T.branchLines>[number]) => l.pts.filter((p) => new RegExp(`^${l.key.replace(/[|]/g, "\\|")}:\\d+$`).test(p.k));

describe("placeBranches", () => {
  it("draws a branch on its sun for every phase machine a live task is in, and only those", () => {
    const scene = board(live()), lines = T.branchLines();
    const phased = scene.tasks.filter((k) => k.h).map((k) => `${(k.host as Galaxy).id}|${k.h!.machine}`);
    expect(phased.length).toBeGreaterThan(0);
    expect(new Set(lines.filter((l) => l.ring === 1).map((l) => `${l.sun}|${l.key.split("|")[1]}`))).toEqual(new Set(phased));
  });

  it("keeps every branch's line clear of every other branch's on its sun", () => {
    mock();
    const lines = T.branchLines();
    expect(lines.some((l) => l.ring === 2)).toBe(true);
    for (const a of lines)
      for (const b of lines) {
        if (a.key >= b.key || a.sun !== b.sun || a.parent === b.key || b.parent === a.key) continue;
        const gap = Math.min(...a.pts.flatMap((p) => b.pts.map((q) => dist(p, q))));
        expect(gap, `${a.key} ~ ${b.key}`).toBeGreaterThan(8);
      }
  });

  it("runs a sub-machine's ray straight out from its parent's station, square to the parent's line", () => {
    const scene = mock(), lines = T.branchLines(), subs = lines.filter((l) => l.ring === 2);
    expect(subs.length).toBeGreaterThan(0);
    for (const s of subs) {
      const g = scene.galaxies[s.sun], parent = lines.find((l) => l.key === s.parent)!, from = stationsOf(parent)[s.pj], ray = s.pts[0];
      const out = { x: from.x - g.x, y: from.y - g.y }, step = { x: ray.x - from.x, y: ray.y - from.y };
      const sin = (out.x * step.y - out.y * step.x) / (Math.hypot(out.x, out.y) * Math.hypot(step.x, step.y));
      expect(Math.abs(sin), s.key).toBeLessThan(0.02);
      expect(out.x * step.x + out.y * step.y, s.key).toBeGreaterThan(0);
    }
  });

  // a 1920 window leaves the canvas 1420 wide beside the rail
  it.each([100, 125, 150].flatMap((s) => [1920, 1420].map((w) => [s, w])))("keeps stations off the Board's curves and every name clear at %i percent text on a %i canvas", (scale, W) => {
    const scene = mock(scale, W);
    const curves = scene.bEdges.filter((e) => e.p0 && e.c && e.p1).flatMap((e) => Array.from({ length: 65 }, (_, i) => sc.bez(e.p0!, e.c!, e.p1!, i / 64)));
    for (const l of T.branchLines().filter((x) => !x.loose))
      for (const p of stationsOf(l)) expect(Math.min(...curves.map((q) => dist(p, q))), p.k).toBeGreaterThanOrEqual(12);
    expect(T.textHits(scene)).toEqual([]);
  });

  it("grows a new branch out over two seconds", () => {
    const scene = board(live(), { secs: 1.5 });
    expect(T.branchLines()).toEqual([]);
    run(scene, 1.5, 0.6);
    expect(T.branchLines().length).toBeGreaterThan(0);
  });

  it("keeps a dot on the lines drawn under it as it rides out onto a sub-machine that is still growing", () => {
    vi.stubGlobal("location", { search: "?mock=1&extra=8&sim=3" });
    const clock = vi.spyOn(performance, "now").mockReturnValue(0);
    board(live(), { secs: 4 });
    clock.mockReturnValue(60_000);
    const scene = board(live(), { secs: 0, from: 4 }), off = new Set<string>();
    for (let t = 4; t <= 10; t += 1 / 60) {
      T.placeBranches(scene, t);
      for (const h of T.offLine(scene)) off.add(h);
    }
    expect(scene.tasks.some((k) => T.branchLines().some((l) => l.ring === 2 && k.h?.machine === l.key.split("|")[2]))).toBe(true);
    expect([...off]).toEqual([]);
  });

  it("traces a dot on a sub-machine back along the line it rode: hub, its phase's stations, then the sub-machine's", () => {
    const scene = mock(), sub = T.branchLines().find((l) => l.ring === 2)!, parent = sub.parent!;
    const k = scene.tasks.find((t) => t.h?.machine === sub.key.split("|")[2])!, trail = T.trailOf(k.id, scene)!;
    expect(trail.pts[0].k).toBe(`${parent}:h`);
    expect(trail.stations.map((s) => s.k)).toContain(`${parent}:${sub.pj}`);
    expect(trail.stations.at(-1)!.k.startsWith(`${sub.key}:`)).toBe(true);
    expect(dist(trail.pts.at(-1)!, k)).toBeLessThan(0.5);
  });

  it("retracts a branch once no task is on its machine, and removes it", () => {
    const snap = live(), scene = board(snap), lines = T.branchLines();
    const key = lines.find((l) => l.ring === 1)!.key, [sun, machine] = key.split("|");
    for (const k of scene.tasks) if (k.h?.machine === machine && (k.host as Galaxy).id === sun) k.h = undefined;
    run(scene, 3, 1);
    expect(T.branchLines().map((l) => l.key)).toContain(key);
    run(scene, 4, 8);
    const left = T.branchLines().map((l) => l.key);
    expect(left).not.toContain(key);
    expect(left).toEqual(lines.map((l) => l.key).filter((k) => k !== key));
  });
});
