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
function board(snap: Snapshot, { scale = 100, secs = 3, from = 0, W = 1920, H = 1080 } = {}): Scene {
  const S = sky.merge(snap), moves = new sky.Moves();
  moves.observe(S, snap.now ?? 0);
  const scene = sc.build({ S, moves, W, H, T: snap.now ?? 0, scale }, { kind: "board" });
  run(scene, from, secs);
  return scene;
}
const run = (scene: Scene, from: number, secs: number) => {
  for (let t = from; t <= from + secs; t += 1 / 60) T.placeBranches(scene, t);
};
const live = () => structuredClone(capture) as unknown as Snapshot;
/** The preview's `?mock=1&extra=8&sim=3` at `scale`% on a `W`-wide canvas: phase tasks on build, deliver and review_fix, and the pair walked from Deliver into the
 *  CI it opens, which branches off Deliver's station. */
function mock(scale = 100, W = 1920, H = 1080): Scene {
  vi.stubGlobal("location", { search: "?mock=1&extra=8&sim=3" });
  const clock = vi.spyOn(performance, "now").mockReturnValue(0);
  board(live(), { scale, W, H });
  clock.mockReturnValue(60_000);
  return board(live(), { scale, W, H, from: 3, secs: 6 });
}
/** The share of phase branch `l`'s line, from the hub, out to its station `s`. */
// a sub-machine's points leave out the parent station it forks from, so it passes that station as `fork`
const upTo = (l: ReturnType<typeof T.branchLines>[number], s: number, fork?: (typeof l.pts)[number]) => {
  const pts = fork ? [fork, ...l.pts] : l.pts, cum = pts.map((_, i) => pts.slice(1, i + 1).reduce((a, p, k) => a + dist(pts[k], p), 0));
  return cum[pts.findIndex((p) => p.k === `${l.key}:${s}`)] / cum.at(-1)!;
};
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

  it("grows no branch into the room of a line still drawn while it leaves the sky", () => {
    const scene = mock(), line = T.branchLines().find((l) => l.ring === 1)!, st = stationsOf(line)[0];
    const riders = scene.tasks.filter((k) => k.h?.ring1 && `${(k.host as Galaxy).id}|${k.h.machine}` === line.key);
    expect(riders.length).toBeGreaterThan(0);
    // a name printed over a station uproots the branch: its line stays drawn while its dots glide back off it
    (scene.hangars ??= []).push({ x0: st.x - 4, y0: st.y - 4, x1: st.x + 4, y1: st.y + 4, of: `${line.sun}/name` });
    T.placeBranches(scene, 9.1);
    expect(T.branchLines(0).find((l) => l.key === line.key)!.leaving).toBe(true);
    // the name moves off again, so its room is the one the new phase prefers
    scene.hangars.pop();
    // meanwhile one of its tasks opens a phase of its own, which wants to sit where that line still stands
    const k = riders[0], fresh = `${line.sun}|fresh`;
    k.h = { ...k.h!, machine: "fresh" };
    const drawn = (l: ReturnType<typeof T.branchLines>[number]) => {
      const cum = l.pts.map((_, i) => l.pts.slice(1, i + 1).reduce((a, p, n) => a + dist(l.pts[n], p), 0));
      return l.ext > 0 ? l.pts.filter((_, i) => cum[i] <= l.ext * cum.at(-1)!) : [];
    };
    let gap = Infinity, grew = false;
    for (let t = 9.1 + 1 / 60; t < 16; t += 1 / 60) {
      T.placeBranches(scene, t);
      const lines = T.branchLines(0), old = lines.find((l) => l.key === line.key && l.leaving), mine = lines.find((l) => l.key === fresh);
      grew ||= !!mine && mine.ext > 0;
      if (old && mine) gap = Math.min(gap, ...drawn(old).flatMap((p) => drawn(mine).map((q) => dist(p, q))));
      // nothing is left to measure once the line has left the sky and the new phase has grown
      if (grew && !old) break;
    }
    expect(grew, "the new phase grows").toBe(true);
    expect(gap, "clear of the line leaving").toBeGreaterThan(8);
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
        expect(dist(p, g) - g.edge, p.k).toBeLessThanOrEqual(10 + 5 * 14 + 0.5);
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

  it.each([[1070, 830, 100], [1070, 830, 125], [1070, 830, 150], [1318, 830, 100], [1318, 830, 150]])("keeps every branch, and every sun its branches stand on, on screen at fit on a %i x %i canvas at %i% text", (W, H, scale) => {
    const scene = mock(scale, W, H), v = fitLevel(scene, W, H);
    const on = (p: Pt) => {
      const s = { x: p.x * v.k + v.x, y: p.y * v.k + v.y };
      return s.x > 0 && s.x < W && s.y > 0 && s.y < H;
    };
    for (const l of T.branchLines()) {
      const g = scene.galaxies[l.sun];
      expect(on({ x: g.x - g.r, y: g.y - g.r }) && on({ x: g.x + g.r, y: g.y + g.r }), `${l.sun}'s sun`).toBe(true);
      for (const p of l.pts) expect(on(p), `${p.k}`).toBe(true);
    }
  });

  it("opens a branch after the page has loaded over 0.6 s on an ease, slow at both ends, out to the station its dot is on", () => {
    const scene = sc.build({ S: sky.merge(live()), moves: new sky.Moves(), W: 1920, H: 1080, T: 0, scale: 100 }, { kind: "board" }), ext: number[] = [];
    const held = scene.tasks.filter((k) => k.h).map((k) => [k, k.h] as const);
    for (const [k] of held) k.h = undefined;
    T.placeBranches(scene, 0);
    for (const [k, h] of held) k.h = h;
    const one = () => T.branchLines(0).filter((l) => l.ring === 1).sort((a, b) => (a.key < b.key ? -1 : 1))[0];
    for (let i = 1; i <= 45; i++) {
      T.placeBranches(scene, i / 60);
      ext.push(one()?.ext ?? 0);
    }
    // a phase branch's dots sit short of its last station, so it opens part way: each frame is measured as a share of where it stops
    const end = ext.at(-1)!;
    expect(end).toBeLessThan(1);
    ext.forEach((e, i) => (ext[i] = e / end));
    expect(ext[5], "0.1 s").toBeLessThan(0.1);
    expect(ext[17], "0.3 s").toBeGreaterThan(0.45);
    expect(ext[17], "0.3 s").toBeLessThan(0.55);
    expect(ext[29], "0.5 s").toBeGreaterThan(0.9);
    expect(ext[36], "0.6 s").toBe(1);
  });

  it("draws every branch, sub-machines too, out to the furthest station a dot or a sub-machine on it has reached on the first frame after the page loads", () => {
    const scene = sc.build({ S: sky.merge(live()), moves: new sky.Moves(), W: 1920, H: 1080, T: 0, scale: 100 }, { kind: "board" });
    const sun = (scene.tasks.find((k) => k.h)!.host as Galaxy).id, mine = scene.tasks.filter((k) => (k.host as Galaxy).id === sun);
    const steps = (n: number) => Array.from({ length: n }, (_, i) => `s${i}`);
    mine[0].h = { machine: "deliver", steps: steps(5), j: 1, ring1: true };
    mine[1].h = { machine: "ci", steps: steps(4), j: 1, ring1: false, side: { machine: "deliver", steps: steps(5), j: 3 } };
    T.placeBranches(scene, 0);
    const lines = T.branchLines(0), at = (key: string) => lines.find((l) => l.key === key)!;
    expect(at(`${sun}|deliver`).ext).toBeCloseTo(upTo(at(`${sun}|deliver`), 3), 6);
    const fork = at(`${sun}|deliver`).pts.find((p) => p.k === `${sun}|deliver:3`)!;
    expect(at(`${sun}|deliver|ci`).ext).toBeCloseTo(upTo(at(`${sun}|deliver|ci`), 1, fork), 6);
    expect(at(`${sun}|deliver|ci`).ext).toBeLessThan(1);
    expect(T.offLine(scene, 0.5)).toEqual([]);
  });

  it("grows a branch out to the next station only as its dot moves there, over 0.6 s", () => {
    const scene = sc.build({ S: sky.merge(live()), moves: new sky.Moves(), W: 1920, H: 1080, T: 0, scale: 100 }, { kind: "board" });
    const sun = (scene.tasks.find((k) => k.h)!.host as Galaxy).id, mine = scene.tasks.filter((k) => (k.host as Galaxy).id === sun);
    const steps = Array.from({ length: 5 }, (_, i) => `s${i}`);
    mine[0].h = { machine: "deliver", steps, j: 0, ring1: true };
    run(scene, 0, 2);
    const line = () => T.branchLines(0).find((l) => l.key === `${sun}|deliver`)!;
    const first = line().ext;
    expect(first).toBeCloseTo(upTo(line(), 0), 6);
    mine[0].h = { machine: "deliver", steps, j: 2, ring1: true };
    run(scene, 2 + 1 / 60, 0.25);
    expect(line().ext).toBeGreaterThan(first);
    expect(line().ext).toBeLessThan(upTo(line(), 2));
    run(scene, 2.3, 1);
    expect(line().ext).toBeCloseTo(upTo(line(), 2), 6);
  });

  it("after a resync, shows the steps a task took while no frame was drawn as they stand, gliding and growing nothing", () => {
    const scene = sc.build({ S: sky.merge(live()), moves: new sky.Moves(), W: 1920, H: 1080, T: 0, scale: 100 }, { kind: "board" });
    const sun = (scene.tasks.find((k) => k.h)!.host as Galaxy).id, mine = scene.tasks.filter((k) => (k.host as Galaxy).id === sun);
    const steps = Array.from({ length: 5 }, (_, i) => `s${i}`);
    mine[0].h = { machine: "deliver", steps, j: 0, ring1: true };
    run(scene, 0, 2);
    // the tab is hidden, or another view is shown, while the task walks on through its phase and into a sub-machine
    mine[0].h = { machine: "ci", steps: steps.slice(0, 4), j: 2, ring1: false, side: { machine: "deliver", steps, j: 3 } };
    T.resyncBranches();
    expect(T.placeBranches(scene, 60), "still animating").toBe(false);
    expect(mine[0].moving).toBe(false);
    const lines = T.branchLines(0), at = (key: string) => lines.find((l) => l.key === key)!;
    expect(at(`${sun}|deliver`).ext).toBeCloseTo(upTo(at(`${sun}|deliver`), 3), 6);
    const fork = at(`${sun}|deliver`).pts.find((p) => p.k === `${sun}|deliver:3`)!;
    expect(at(`${sun}|deliver|ci`).ext).toBeCloseTo(upTo(at(`${sun}|deliver|ci`), 2, fork), 6);
    expect(T.offLine(scene, 0.5)).toEqual([]);
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
    for (let t = 9.1; t < 14 && ext() === sub.ext; t += 1 / 60) T.placeBranches(scene, t);
    expect(ext()).toBeGreaterThan(0);
    expect(ext()).toBeLessThan(sub.ext);
    text.mockClear();
    T.drawBranches(dc(null), d, scene, stationsOf(sub)[0]);
    T.drawBranches(dc({ kind: "task", o: k }), d, scene, null);
    expect(printed()).toEqual([]);
  });

  it("traces a dot on a sub-machine back along the line it rode: hub, its phase's stations, then the sub-machine's", () => {
    const scene = mock(), sub = T.branchLines().find((l) => l.ring === 2)!, parent = sub.parent!;
    const k = scene.tasks.find((t) => t.h?.machine === sub.key.split("|")[2])!, route = T.routeOf(k.id, scene)!;
    expect(route.run[0].k).toBe(`${parent}:h`);
    expect(route.run.map((n) => n.k)).toContain(`${parent}:${sub.pj}`);
    expect(route.run.filter((n) => n.step).at(-1)!.k.startsWith(`${sub.key}:`)).toBe(true);
    expect(dist(route.end, k)).toBeLessThan(0.5);
  });

  it("tears a branch down over 0.6 s on an ease once no task is on its machine, and removes it", () => {
    const snap = live(), scene = board(snap), lines = T.branchLines();
    const { key, ext: top } = lines.find((l) => l.ring === 1)!, [sun, machine] = key.split("|"), ext: number[] = [];
    for (const k of scene.tasks) if (k.h?.machine === machine && (k.host as Galaxy).id === sun) k.h = undefined;
    // the dots that rode it glide off first, each keeping the branch up until it is clear
    for (let i = 0; i < 720; i++) {
      T.placeBranches(scene, 3 + i / 60);
      ext.push((T.branchLines(0).find((l) => l.key === key)?.ext ?? 0) / top);
    }
    const start = ext.findIndex((e) => e < 1);
    expect(ext[0]).toBe(1);
    expect(start).toBeGreaterThan(0);
    expect(ext[start + 5], "0.1 s").toBeGreaterThan(0.9);
    expect(ext[start + 17], "0.3 s").toBeGreaterThan(0.45);
    expect(ext[start + 17], "0.3 s").toBeLessThan(0.55);
    expect(ext[start + 37], "0.6 s").toBe(0);
    expect(T.branchLines().map((l) => l.key)).toEqual(lines.map((l) => l.key).filter((k) => k !== key));
  });

  it("names one station per state in a machine's configuration, in step order, or the one step it is on", () => {
    const h = { machine: "qa", steps: ["a", "b", "c", "d"], j: 1, ring1: true };
    expect(T.stationOf({ ...h, config: ["d", "a"] })).toEqual([0, 3]);
    expect(T.stationOf({ ...h, config: ["c", "c"] })).toEqual([2]);
    expect(T.stationOf(h)).toEqual([1]);
    expect(T.stationOf({ ...h, config: ["gone"] })).toEqual([1]);
  });

  it("draws one dot on each station of a task in parallel states, and no more", () => {
    const scene = mock(), k = scene.tasks.find((t) => t.h?.ring1 && t.h.machine === "deliver")!, h = k.h!, sun = (k.host as Galaxy).id;
    expect(T.dotsOf(k.id)).toHaveLength(1);
    k.h = { ...h, config: [h.steps[0], h.steps.at(-1)!] };
    run(scene, 9, 3);
    const line = T.branchLines().find((l) => l.key === `${sun}|deliver`)!, dots = T.dotsOf(k.id);
    expect(dots).toHaveLength(2);
    [0, h.steps.length - 1].forEach((s, n) => expect(dist(dots[n], line.pts.find((p) => p.k === `${line.key}:${s}`)!), `step ${s}`).toBeLessThan(1));
    k.h = { ...h, config: [h.steps[0]] };
    run(scene, 12, 3);
    expect(T.dotsOf(k.id)).toHaveLength(1);
  });

  it("stacks dots sharing a station one step further out from the sun each, by id order", () => {
    const scene = mock(), by = new Map<string, string[]>();
    for (const k of scene.tasks) if (k.h) by.set(`${(k.host as Galaxy).id}|${k.h.machine}|${k.h.j}`, [...(by.get(`${(k.host as Galaxy).id}|${k.h.machine}|${k.h.j}`) ?? []), k.id]);
    const shared = [...by.entries()].filter(([, ids]) => ids.length > 1);
    expect(shared.length).toBeGreaterThan(0);
    for (const [key, ids] of shared) {
      const g = scene.galaxies[key.split("|")[0]], out = ids.sort().map((id) => dist(T.dotsOf(id)[0], g));
      out.slice(1).forEach((d, i) => expect(d - out[i], key).toBeCloseTo(5, 0));
    }
  });

  it("keeps a dot past the third on a crowded station on its line, gliding in or out, never out beyond the branch", () => {
    const scene = sc.build({ S: sky.merge(live()), moves: new sky.Moves(), W: 1920, H: 1080, T: 0, scale: 100 }, { kind: "board" });
    const sun = (scene.tasks.find((k) => k.h)!.host as Galaxy).id, mine = scene.tasks.filter((k) => (k.host as Galaxy).id === sun);
    const steps = Array.from({ length: 5 }, (_, i) => `s${i}`), crowd = [...mine].sort((a, b) => (a.id < b.id ? -1 : 1)).slice(0, 7);
    expect(crowd).toHaveLength(7);
    for (const k of mine) k.h = undefined;
    crowd.forEach((k, i) => (k.h = { machine: "deliver", steps, j: i < 6 ? 1 : 3, ring1: true }));
    run(scene, 0, 3);
    const g = scene.galaxies[sun], line = () => T.branchLines().find((l) => l.key === `${sun}|deliver`)!;
    const beyond = () => crowd.flatMap((k) => (Math.min(...stationsOf(line()).map((s) => dist(T.dotsOf(k.id)[0], s))) > 2 * 5 + 0.5 && !k.moving ? [k.id] : []));
    expect(beyond(), "settled").toEqual([]);
    const off = new Set<string>(), far = (k: (typeof crowd)[number]) => dist(T.dotsOf(k.id)[0], g);
    let reach = 0;
    // the last dot by id rides in onto the crowded station as its seventh, then the sixth leaves it for the far station
    crowd[6].h = { machine: "deliver", steps, j: 1, ring1: true };
    for (let t = 3; t <= 6; t += 1 / 60) {
      T.placeBranches(scene, t);
      for (const h of T.offLine(scene, 0.5)) off.add(h);
      reach = Math.max(reach, far(crowd[6]));
    }
    crowd[5].h = { machine: "deliver", steps, j: 3, ring1: true };
    for (let t = 6; t <= 9; t += 1 / 60) {
      T.placeBranches(scene, t);
      for (const h of T.offLine(scene, 0.5)) off.add(h);
      reach = Math.max(reach, far(crowd[5]));
    }
    expect([...off]).toEqual([]);
    expect(reach, "no further out than the third dot's spot").toBeLessThanOrEqual(Math.max(...stationsOf(line()).map((s) => dist(s, g))) + 2 * 5 + 0.5);
    expect(beyond(), "settled again").toEqual([]);
  });

  it("glides a dot from one station to the next at 98 px/s", () => {
    const scene = mock(), k = scene.tasks.find((t) => t.h?.ring1 && t.h.machine === "deliver")!, h = k.h!;
    const j = (h.j + 2) % h.steps.length;
    k.h = { ...h, j, config: [h.steps[j]] };
    const step: number[] = [];
    let last = T.dotsOf(k.id)[0];
    for (let t = 9; t < 14; t += 1 / 60) {
      T.placeBranches(scene, t);
      const d = T.dotsOf(k.id)[0];
      step.push(dist(d, last));
      last = d;
    }
    const moving = step.filter((d) => d > 0.01);
    // two stations on a lane 14 px out is about 30 px: some 18 frames at 98 px/s
    expect(moving.length).toBeGreaterThan(12);
    // constant speed, never slower on a longer way and never faster on a shorter
    for (const d of moving.slice(1, -1)) expect(d).toBeCloseTo(98 / 60, 1);
  });

  it("glides the dots of a branch placed afresh to its new place, never jumping one", () => {
    const scene = mock(), line = T.branchLines().find((l) => l.ring === 1)!, st = stationsOf(line)[0];
    const riders = scene.tasks.filter((k) => k.h?.ring1 && `${(k.host as Galaxy).id}|${k.h.machine}` === line.key);
    expect(riders.length).toBeGreaterThan(0);
    // a hangar name printed over a station leaves the branch no place that fits, so it is placed afresh
    (scene.hangars ??= []).push({ x0: st.x - 4, y0: st.y - 4, x1: st.x + 4, y1: st.y + 4, of: `${line.sun}/name` });
    const prev = riders.map((k) => T.dotsOf(k.id)[0]), jumps: number[] = [], ext: number[] = [], gliding: boolean[] = [], onLine: boolean[] = [], old = stationsOf(line);
    // the app rebuilds the scene each frame, so each task starts it back at its Board place
    const home = scene.tasks.map((k) => ({ x: k.x, y: k.y }));
    // the riders' Board places lie off the line, on the far side of the sun (they were drawn on their stations when mock() placed them)
    const g = scene.galaxies[line.sun];
    riders.forEach((k, i) => Object.assign(home[scene.tasks.indexOf(k)], { x: g.x + 260 * Math.cos(line.th + Math.PI + i / 4), y: g.y + 260 * Math.sin(line.th + Math.PI + i / 4) }));
    for (let t = 9.1; t < 24; t += 1 / 60) {
      scene.tasks.forEach((k, i) => Object.assign(k, home[i]));
      T.placeBranches(scene, t);
      gliding.push(scene.tasks.some((k) => k.moving));
      onLine.push(riders.some((k) => old.some((o) => dist(o, T.dotsOf(k.id)[0]) < 8)));
      ext.push(T.branchLines(0).find((l) => l.key === line.key)?.ext ?? 0);
      riders.forEach((k, i) => {
        const d = T.dotsOf(k.id)[0];
        jumps.push(dist(d, prev[i]));
        prev[i] = d;
      });
    }
    expect(T.branchLines().find((l) => l.key === line.key)!.th, "re-placed").not.toBe(line.th);
    // the old line stays drawn, whole, while its dots glide back off it, then tears down and grows out again in the new place
    const fall = ext.findIndex((e, i) => i && e < ext[i - 1]);
    expect(fall, "the line tears down").toBeGreaterThan(0);
    expect(ext[fall - 1], "whole until its dots have left").toBe(line.ext);
    expect(gliding[fall] || onLine[fall], "a dot still on it when it tears down").toBe(false);
    expect(ext.slice(fall).findIndex((e) => e === 0), "an ease over 0.6 s, not a cut").toBeGreaterThanOrEqual(0.6 * 60 - 2);
    expect(ext.slice(fall).some((e) => e === 0), "gone before it regrows").toBe(true);
    expect(Math.max(...jumps)).toBeLessThan(98 / 60 + 0.1);
    expect(jumps.filter((d) => d > 0.01).length, "glided").toBeGreaterThan(10);
    const placed = stationsOf(T.branchLines().find((l) => l.key === line.key)!);
    riders.forEach((k, i) => expect(placed.some((st) => dist(st, prev[i]) < 8), k.id).toBe(true));
  });

  it("draws, for each phase agent of the live snapshot, a dot on the station of every state of its machine's configuration", () => {
    const scene = mock(), lines = new Map(T.branchLines().map((l) => [l.key, l]));
    const phased = scene.tasks.filter((k) => k.h && k.alpha !== 0);
    expect(phased.length).toBeGreaterThan(0);
    for (const k of phased) {
      const h = k.h!, sun = h.ring1 || !h.side ? `${(k.host as Galaxy).id}|${h.machine}` : "", stations = T.stationOf(h);
      expect(T.dotsOf(k.id), k.id).toHaveLength(stations.length);
      if (!sun || !lines.has(sun)) continue;
      T.dotsOf(k.id).forEach((d, n) => {
        const s = lines.get(sun)!.pts.find((p) => p.k === `${sun}:${stations[n]}`)!;
        expect(dist(d, s), `${k.id} on ${h.steps[stations[n]]}`).toBeLessThan(5 * phased.length);
      });
    }
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
