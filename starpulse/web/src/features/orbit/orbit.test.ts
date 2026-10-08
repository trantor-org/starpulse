import { describe, expect, it } from "vitest";
import { petalSpeeds, layoutOrbit, petals, positionAt, separateLabels, type OrbitInput, type OrbitScene } from "./orbit";
import { fitBox, toScreen } from "../../render/zoom";

const TERMS = [{ id: "done", role: "goal" }, { id: "archived", role: "abandoned" }, { id: "needs_attention", role: "parked" }, { id: "waiting", role: "blocked" }];
const WORKING = ["ready", "in_progress", "review", "waiting", "needs_attention"];

const source = (id: string, share: Record<string, number>, over: Partial<OrbitInput["sources"][number]> = {}): OrbitInput["sources"][number] => ({
  id, name: id, shared: true, wip: 6, perDay: 1, cycleDays: 4, terminalShare: share, timeShare: share, ended: {}, ...over,
});

/** A level of `n` terminal suns, or the working states with the terminals standing in a column, over three sources. */
function input(n: number, suns: "terminal" | "working" = "terminal", shares?: Record<string, number>[]): OrbitInput {
  const terms = TERMS.slice(0, n);
  const even = (ids: string[]) => Object.fromEntries(ids.map((id) => [id, 1 / ids.length]));
  const ids = suns === "working" ? WORKING : terms.map((t) => t.id);
  const lean = (first: number) => Object.fromEntries(ids.map((id, i) => [id, i ? (1 - first) / (ids.length - 1) : first]));
  const mix = shares ?? [even(ids), lean(0.7), lean(0)];
  return {
    suns, terminals: terms, working: WORKING, name: (id) => id,
    endedTotals: Object.fromEntries(terms.map((t, i) => [t.id, 40 - 9 * i])),
    taskDays: Object.fromEntries(WORKING.map((id, i) => [id, 12 + 7 * i])),
    sources: [source("a", mix[0], { perDay: 2, cycleDays: 3 }), source("b", mix[1], { perDay: 1, cycleDays: 6 }), source("unattributed", mix[2], { shared: false, perDay: 0.5, cycleDays: 9 })],
    aspect: 1.6,
  };
}

const closes = (path: number[]) => Math.hypot(path[0] - path.at(-2)!, path[1] - path.at(-1)!);

describe("the orbit of one source", () => {
  it.each([1, 2, 3, 4])("closes into one curve round %i sun(s) and reaches each", (n) => {
    const scene = layoutOrbit(input(n));
    for (const b of scene.sources) {
      expect(closes(b.path)).toBeLessThan(0.01); // the petal's ends are a cos(π/2)^p from the centre
      scene.suns.forEach((sun) => {
        const reach = Math.max(...b.path.map((_, i) => (i % 2 ? 0 : (b.path[i] - scene.c.x) * Math.cos(sun.phi) + (b.path[i + 1] - scene.c.y) * Math.sin(sun.phi))));
        expect(reach).toBeGreaterThanOrEqual(Math.hypot(sun.x - scene.c.x, sun.y - scene.c.y) - 1e-6);
      });
    }
  });

  it("is a circle for one sun, a lemniscate for two, a trefoil for three and a clover for four", () => {
    expect([1, 2, 3, 4].map((n) => (n === 1 ? 1 : petals(n).order.length))).toEqual([1, 2, 3, 4]);
    expect(petals(2)).toMatchObject({ m: 2, dir: [1, -1] });
    expect(petals(3).order).toEqual([0, 2, 1]);
  });

  it.each([2, 3, 4])("crosses the centre at most four times faster along one petal than another with %i suns", (n) => {
    const worst = [[0.5, 0.5], [1, 0], [0.9, 0.05, 0.05], [0, 0, 1], [0.7, 0.1, 0.1, 0.1], [0, 0, 0, 1]];
    for (const w of worst) {
      const ids = TERMS.slice(0, n).map((t) => t.id);
      if (w.length !== n) continue;
      const scene = layoutOrbit(input(n, "terminal", [0, 1, 2].map(() => Object.fromEntries(ids.map((id, i) => [id, w[i]])))));
      for (const b of scene.sources) {
        const speeds = petalSpeeds(b);
        expect(Math.max(...speeds) / Math.min(...speeds)).toBeLessThanOrEqual(4);
      }
    }
  });

  it("spends a share of each period in a petal that grows with its share and never reaches zero", () => {
    const [a, b, c] = layoutOrbit(input(2)).sources;
    for (const s of [a, b, c]) expect(s.frac.reduce((x, y) => x + y, 0)).toBeCloseTo(1, 9);
    expect(b.frac[0]).toBeGreaterThan(a.frac[0]);
    expect(c.frac[0]).toBeGreaterThan(0);
    expect(c.frac[0]).toBeLessThan(a.frac[0]);
  });

  it("spends a source with no runs to share by length alone, still a whole period", () => {
    const scene = layoutOrbit(input(3, "terminal", [{}, {}, {}]));
    for (const b of scene.sources) expect(b.frac.reduce((x, y) => x + y, 0)).toBeCloseTo(1, 9);
  });

  it("moves at one speed along a petal, however the petal bends", () => {
    const scene = layoutOrbit(input(3));
    const b = scene.sources[0];
    // the first petal is walked from u = 0 to its share of the period: equal steps cover equal distance
    const end = b.frac[petals(3).order[0]], pts = Array.from({ length: 9 }, (_, i) => positionAt(scene, b, ((i + 0.5) / 9) * end));
    const steps = pts.slice(1).map((p, i) => Math.hypot(p.x - pts[i].x, p.y - pts[i].y));
    expect(Math.max(...steps) / Math.min(...steps)).toBeLessThan(1.1);
  });
});

describe("the suns", () => {
  it("is one sun at the centre, two facing each other, the goal first", () => {
    const one = layoutOrbit(input(1));
    expect(one.suns).toHaveLength(1);
    expect(one.suns[0]).toMatchObject({ x: one.c.x, y: one.c.y });
    const two = layoutOrbit(input(2));
    expect(two.suns.map((s) => s.id)).toEqual(["done", "archived"]);
    expect(two.suns[0].x + two.suns[1].x).toBeCloseTo(2 * two.c.x, 6);
    expect(two.suns[0].y).toBeCloseTo(two.c.y, 6);
  });

  it("draws a sun's size from the runs that ended there, or from the task-days spent there", () => {
    const t = layoutOrbit(input(2));
    expect(t.suns[0].r).toBeGreaterThan(t.suns[1].r);
    const w = layoutOrbit(input(2, "working"));
    expect(w.suns.map((s) => s.id)).toEqual(WORKING);
    expect(w.suns[4].r).toBeGreaterThan(w.suns[0].r);
  });

  it("circles the working states and stands every terminal in a column to the right, the goal on top", () => {
    const w = layoutOrbit(input(2, "working"));
    expect(w.ends.map((e) => e.id)).toEqual(["done", "archived"]);
    expect(w.ends[0].y).toBeLessThan(w.ends[1].y);
    const reach = Math.max(...w.sources.flatMap((b) => b.path.filter((_, i) => i % 2 === 0)), ...w.suns.map((s) => s.x + s.r));
    for (const e of w.ends) expect(e.x - e.r).toBeGreaterThan(reach);
    expect(layoutOrbit(input(2)).ends).toEqual(layoutOrbit(input(2)).suns);
  });
});

// The canvas the page leaves between the folded navigator and the rail
const canvasOf = (vw: number, vh: number) => ({ w: vw - 52 - 250, h: vh });

describe("the card at each window size", () => {
  const cases: [number, number][] = [[1100, 900], [1440, 900], [1920, 1080], [2560, 1440]];
  it.each(cases)("centres the working orbit and keeps the terminal column inside a %i x %i window", (vw, vh) => {
    const cv = canvasOf(vw, vh), scene: OrbitScene = layoutOrbit({ ...input(2, "working"), aspect: cv.w / cv.h });
    const view = fitBox({ x0: scene.box[0], y0: scene.box[1], x1: scene.box[2], y1: scene.box[3] }, cv.w, cv.h);
    expect(Math.abs(toScreen(view, scene.c).x - cv.w / 2)).toBeLessThan(1);
    for (const e of scene.ends) {
      const p = toScreen(view, e);
      expect(p.x + e.r * view.k).toBeLessThanOrEqual(cv.w);
      expect(p.x - e.r * view.k).toBeGreaterThanOrEqual(0);
      expect(p.y - e.r * view.k).toBeGreaterThanOrEqual(0);
      expect(p.y + e.r * view.k).toBeLessThanOrEqual(cv.h);
    }
  });

  it.each(cases)("keeps every source's label clear of the others' at %i x %i, all the way round", (vw, vh) => {
    const cv = canvasOf(vw, vh), scene = layoutOrbit({ ...input(3), aspect: cv.w / cv.h });
    const view = fitBox({ x0: scene.box[0], y0: scene.box[1], x1: scene.box[2], y1: scene.box[3] }, cv.w, cv.h);
    for (let t = 0; t < 300; t += 0.7) {
      const rects = scene.sources.map((b) => {
        const p = positionAt(scene, b, ((t / b.period + b.phase) % 1 + 1) % 1);
        return { x: p.x, y: p.y + b.r + 37.5 / view.k, w: (Math.max(b.name.length, 9) * 12.5 * 0.56 + 6) / view.k, h: 34 / view.k };
      });
      const off = separateLabels(rects);
      const placed = rects.map((r, i) => ({ ...r, y: r.y + off[i] }));
      for (let i = 0; i < placed.length; i++)
        for (let j = i + 1; j < placed.length; j++) {
          const a = placed[i], b = placed[j];
          expect(Math.abs(a.x - b.x) < (a.w + b.w) / 2 && Math.abs(a.y - b.y) < (a.h + b.h) / 2).toBe(false);
        }
    }
  });
});
