import { beforeEach, describe, expect, it, vi } from "vitest";
import capture from "./fixtures/events-snapshot.json";
import type { Snapshot } from "../api";
import type { Galaxy, Pt, Scene } from "./scene";
import type { Drawing, Hover } from "./draw";
import { fitLevel } from "./zoom";

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

  // the demo's In Progress: three phases, and five sub-machines, three of them opened off one CI station, the longest thirteen steps
  it.each([[1920, 1080], [1420, 860]])("gives sub-machines opened off one station their own lanes or sides on a %ix%i canvas, never one arc", (W, H) => {
    vi.stubGlobal("location", { search: "?mock=1&extra=8&sim=3" });
    const scene = sc.build({ S: sky.merge(live()), moves: new sky.Moves(), W, H, T: 0, scale: 100 }, { kind: "board" });
    const sun = (scene.tasks.find((k) => k.h)!.host as Galaxy).id, mine = scene.tasks.filter((k) => (k.host as Galaxy).id === sun);
    for (const k of scene.tasks) k.h = undefined;
    const steps = (n: number) => Array.from({ length: n }, (_, i) => `s${i}`), phases: [string, number][] = [["ci", 6], ["dependency-review", 5], ["review-triage", 5]];
    const subs: [string, number, string, number][] = [["harness", 3, "review-triage", 2], ["harness", 3, "dependency-review", 3], ["harness", 3, "ci", 1], ["docs-audit", 5, "ci", 1], ["delivery", 13, "ci", 1]];
    phases.forEach(([m, n], i) => (mine[i].h = { machine: m, steps: steps(n), j: 1, ring1: true }));
    subs.forEach(([m, n, p, j], i) => (mine[3 + i].h = { machine: m, steps: steps(n), j: 0, ring1: false, side: { machine: p, steps: steps(phases.find((f) => f[0] === p)![1]), j } }));
    run(scene, 0, 8);
    const lines = T.branchLines();
    expect(lines.filter((l) => l.parent === `${sun}|ci`)).toHaveLength(3);
    // siblings share the ray out from their station, so their own runs are measured from the turn onto their lanes
    const run_ = (l: (typeof lines)[number]) => l.pts.filter((p) => !/:(s\d+|r)$/.test(p.k));
    for (const a of lines)
      for (const b of lines) {
        if (a.key >= b.key || a.parent === b.key || b.parent === a.key) continue;
        const sib = a.parent && a.parent === b.parent && a.pj === b.pj, [pa, pb] = sib ? [run_(a), run_(b)] : [a.pts, b.pts];
        expect(Math.min(...pa.flatMap((p) => pb.map((q) => dist(p, q)))), `${a.key} ~ ${b.key}`).toBeGreaterThan(8);
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
  it.each([100, 125, 150].flatMap((s) => [1920, 1420].map((w) => [s, w])))("keeps stations off the Board's curves at %i percent text on a %i canvas", (scale, W) => {
    const scene = mock(scale, W);
    const curves = scene.bEdges.filter((e) => e.p0 && e.c && e.p1).flatMap((e) => Array.from({ length: 65 }, (_, i) => sc.bez(e.p0!, e.c!, e.p1!, i / 64)));
    for (const l of T.branchLines().filter((x) => !x.loose))
      for (const p of stationsOf(l)) expect(Math.min(...curves.map((q) => dist(p, q))), p.k).toBeGreaterThanOrEqual(12);
  });

  // the demo's In Progress opens seven sub-machines off one phase at once: more than its lanes hold, so those with no room wait on their orbits
  it.each([[1920, 1080], [1420, 860]])("keeps a crowd of sub-machines within a few lanes of the hub, on the fitted %ix%i canvas and clear of each other", (W, H) => {
    vi.stubGlobal("location", { search: "?mock=1&extra=8&sim=3" });
    const scene = sc.build({ S: sky.merge(live()), moves: new sky.Moves(), W, H, T: 0, scale: 100 }, { kind: "board" });
    run(scene, 0, 3);
    const deliver = scene.tasks.find((k) => k.h?.ring1 && k.h.machine === "deliver")!.h!, sun = (scene.tasks.find((k) => k.h)!.host as Galaxy).id;
    scene.tasks
      .filter((k) => (k.host as Galaxy).id === sun)
      .slice(0, 14)
      .forEach((k, i) => (k.h = { machine: `sub${i % 7}`, steps: ["queued", "running", "failing", "passing"], j: i % 4, ring1: false, side: { machine: "deliver", steps: deliver.steps, j: i % deliver.steps.length } }));
    run(scene, 3, 6);
    const v = fitLevel(scene, W, H), lines = T.branchLines();
    expect(lines.filter((l) => l.ring === 2).length).toBeGreaterThanOrEqual(5);
    const run_ = (l: (typeof lines)[number]) => l.pts.filter((p) => !/:(s\d+|r)$/.test(p.k));
    for (const a of lines)
      for (const b of lines) {
        if (a.key >= b.key || a.sun !== b.sun || a.parent === b.key || b.parent === a.key) continue;
        const sib = a.parent && a.parent === b.parent && a.pj === b.pj, [pa, pb] = sib ? [run_(a), run_(b)] : [a.pts, b.pts];
        expect(Math.min(...pa.flatMap((p) => pb.map((q) => dist(p, q)))), `${a.key} ~ ${b.key}`).toBeGreaterThan(8);
      }
    for (const l of lines)
      for (const p of l.pts) {
        const g = scene.galaxies[l.sun];
        const s = { x: p.x * v.k + v.x, y: p.y * v.k + v.y };
        expect(s.x > 0 && s.x < W && s.y > 0 && s.y < H, `${p.k} at ${Math.round(s.x)},${Math.round(s.y)}`).toBe(true);
        // ring-2 lanes start one past their parent's, which takes one of the first three
        expect(dist(p, g) - g.edge, p.k).toBeLessThanOrEqual(20 + 5 * 28 + 0.5);
      }
  });

  // a window made shorter keeps the suns where they were on the sky but shows less of it
  it("re-places a branch the window's new shape would leave off the canvas", () => {
    vi.stubGlobal("location", { search: "?mock=1&extra=8&sim=3" });
    const lay = (H: number, from: number) => {
      const scene = sc.build({ S: sky.merge(live()), moves: new sky.Moves(), W: 1420, H, T: 0, scale: 100 }, { kind: "board" });
      run(scene, from, 3);
      const deliver = scene.tasks.find((k) => k.h?.ring1 && k.h.machine === "deliver")!.h!, sun = (scene.tasks.find((k) => k.h)!.host as Galaxy).id;
      scene.tasks
        .filter((k) => (k.host as Galaxy).id === sun)
        .slice(0, 14)
        .forEach((k, i) => (k.h = { machine: `sub${i % 7}`, steps: ["queued", "running", "failing", "passing"], j: i % 4, ring1: false, side: { machine: "deliver", steps: deliver.steps, j: i % deliver.steps.length } }));
      run(scene, from + 3, 6);
      return scene;
    };
    lay(1080, 0);
    const scene = lay(640, 9), v = fitLevel(scene, 1420, 640);
    for (const l of T.branchLines())
      for (const p of l.pts) {
        const s = { x: p.x * v.k + v.x, y: p.y * v.k + v.y };
        expect(s.x > 0 && s.x < 1420 && s.y > 0 && s.y < 640, `${p.k} at ${Math.round(s.x)},${Math.round(s.y)}`).toBe(true);
      }
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
      for (const h of T.offLine(scene, 0.5)) off.add(h);
    }
    expect(scene.tasks.some((k) => T.branchLines().some((l) => l.ring === 2 && k.h?.machine === l.key.split("|")[2]))).toBe(true);
    expect([...off]).toEqual([]);
  });

  it("places a branch once and grows it out square from where its parent's tip has reached", () => {
    vi.stubGlobal("location", { search: "?mock=1&extra=8&sim=3" });
    const clock = vi.spyOn(performance, "now").mockReturnValue(0);
    let scene = board(live(), { secs: 0 });
    const first = new Map<string, string>(), bad = new Set<string>();
    const frame = (t: number) => {
      T.placeBranches(scene, t);
      const lines = T.branchLines(0);
      for (const l of lines) {
        const g = scene.galaxies[l.sun], was = first.get(l.key) ?? `${l.th}@${l.lane}@${l.dir}`;
        first.set(l.key, was);
        if (!Number.isFinite(l.th) || was !== `${l.th}@${l.lane}@${l.dir}`) bad.add(`${l.key} moved`);
        // each stretch of a line runs straight out from the sun or round it, never slantwise
        l.pts.forEach((q, i) => {
          if (!i) return;
          const p = l.pts[i - 1], da = Math.atan2(q.y - g.y, q.x - g.x) - Math.atan2(p.y - g.y, p.x - g.x);
          if (Math.abs(Math.atan2(Math.sin(da), Math.cos(da))) > 1e-6 && Math.abs(dist(q, g) - dist(p, g)) > 1e-6) bad.add(`${l.key} slant at ${q.k}`);
        });
        const par = lines.find((o) => o.key === l.parent);
        if (!par || !l.ext) continue;
        const cum = par.pts.reduce<number[]>((c, q, i) => [...c, i ? c[i - 1] + dist(q, par.pts[i - 1]) : 0], []), at = par.pts.findIndex((q) => q.k === `${par.key}:${l.pj}`);
        if (par.ext * cum.at(-1)! < cum[at] - 0.01) bad.add(`${l.key} ahead of ${par.key}`);
      }
    };
    for (let t = 0; t <= 4; t += 1 / 60) frame(t);
    clock.mockReturnValue(60_000);
    scene = board(live(), { secs: 0, from: 4 });
    for (let t = 4; t <= 12; t += 1 / 60) frame(t);
    expect(T.branchLines().some((l) => l.ring === 2)).toBe(true);
    expect([...bad]).toEqual([]);
  });

  it("prints a branch's machine name and its riders' steps only while the pointer is on it or on a dot riding it, never one name over another", () => {
    const scene = mock(), text = vi.fn(), noop = () => {};
    const cx = new Proxy({}, { get: (_, p) => (p === "createRadialGradient" ? () => ({ addColorStop: noop }) : noop), set: () => true }) as unknown as CanvasRenderingContext2D;
    const d = { circle: noop, dot: noop, text, labPx: (n: number) => n } as unknown as Drawing;
    const dc = (hover: Hover | null) => ({ cx, K: 1, ZS: 1, clock: 0, scale: 100, hover });
    const printed = () => text.mock.calls.map((c) => c[0] as string);
    T.drawBranches(dc(null), d, scene, null);
    expect(printed()).toEqual([]);
    const sub = T.branchLines().find((l) => l.ring === 2)!, [, phase, machine] = sub.key.split("|"), k = scene.tasks.find((t) => t.h?.machine === machine)!;
    T.drawBranches(dc({ kind: "task", o: k }), d, scene, null);
    expect(printed()).toEqual(expect.arrayContaining([phase, machine, k.h!.steps[k.h!.j].replace(/_/g, " ")]));
    const boxes = text.mock.calls.map((c) => {
      const [s, x, y, h, , align] = c as [string, number, number, number, string, CanvasTextAlign], w = (sc.textW(s, 9) * h) / 9, x0 = align === "left" ? x : align === "right" ? x - w : x - w / 2;
      return { s, x0, x1: x0 + w, y0: y - h / 2, y1: y + h / 2 };
    });
    for (const a of boxes) for (const b of boxes) if (a !== b) expect(a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1, `${a.s} on ${b.s}`).toBe(false);
    text.mockClear();
    T.drawBranches(dc(null), d, scene, stationsOf(sub)[0]);
    expect(printed()).toContain(machine);
    // once no task is on it the branch retracts, and the pointer still on its line prints nothing
    for (const t of scene.tasks) if (t.h?.machine === machine) t.h = undefined;
    const ext = () => T.branchLines(0).find((l) => l.key === sub.key)?.ext ?? 0;
    for (let t = 9.1; t < 14 && ext() === 1; t += 1 / 60) T.placeBranches(scene, t);
    expect(ext()).toBeGreaterThan(0);
    expect(ext()).toBeLessThan(1);
    text.mockClear();
    T.drawBranches(dc(null), d, scene, stationsOf(sub)[0]);
    T.drawBranches(dc({ kind: "task", o: k }), d, scene, null);
    expect(printed()).toEqual([]);
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

  it("keeps every branch clear of the orbiter of whichever DAG has its turn", async () => {
    const scene = mock(), D = await import("./dagTies"), orb = 7 / fitLevel(scene, 1920, 1080).k;
    // one orbiter per state, just off its ring where a hangar's DAG docks
    const orbs = Object.entries(scene.galaxies).map(([id, g]) => ({ dag: `dagu/${id}`, x: g.x + g.R * 1.3, y: g.y - g.R * 1.3 }));
    scene.hangars = orbs.map((o) => ({ of: `hangar:${o.dag}`, x0: o.x - orb, y0: o.y - orb, x1: o.x + orb, y1: o.y + orb }));
    run(scene, 10, 6);
    const pts = T.branchLines().flatMap((l) => l.pts), dags = orbs.map((o) => o.dag);
    expect(pts.length).toBeGreaterThan(0);
    for (let i = 0; i < dags.length; i++) {
      const o = orbs.find((x) => x.dag === D.dagTurn(dags, i * D.TURN)!.dag)!;
      expect(Math.min(...pts.map((p) => dist(p, o))), o.dag).toBeGreaterThan(orb);
    }
  });
});
