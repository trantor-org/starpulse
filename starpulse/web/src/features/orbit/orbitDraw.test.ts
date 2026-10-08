import { describe, expect, it } from "vitest";
import { layoutOrbit, type OrbitInput } from "./orbit";
import { arrivalDays, bottleneck, describeHover, drawOrbit, hitOrbit, TAIL, type Frame } from "./orbitDraw";

const DAY = 86400;
const TERMS = [{ id: "done", role: "goal" }, { id: "archived", role: "abandoned" }];
const WORKING = ["ready", "in_progress"];

function input(suns: "terminal" | "working" = "terminal"): OrbitInput {
  const t = { done: 0.7, archived: 0.3 }, w = { ready: 0.25, in_progress: 0.75 };
  const src = (id: string, shared: boolean, perDay: number) => ({ id, name: id, shared, wip: 6, perDay, cycleDays: 4, ended: { done: 7, archived: 3 }, terminalShare: t, timeShare: w });
  return {
    suns, terminals: TERMS, working: WORKING, name: (id) => id.toUpperCase(),
    endedTotals: { done: 14, archived: 6 }, taskDays: { ready: 5, in_progress: 15 },
    sources: [src("alpha", true, 2), src("beta", true, 1), src("unattributed", false, 0.5)], aspect: 1.6,
  };
}

/** A canvas context that records the text it draws and how many arcs, and accepts everything else. */
function recorder() {
  const texts: string[] = [], calls: Record<string, number> = {}, store: Record<string, unknown> = {};
  const cx = new Proxy({} as Record<string, unknown>, {
    get: (_, p: string) => {
      if (p in store) return store[p];
      if (p === "createRadialGradient" || p === "createLinearGradient") return () => ({ addColorStop() {} });
      if (p === "measureText") return (s: string) => ({ width: s.length * 6 });
      return (...a: unknown[]) => {
        calls[p] = (calls[p] ?? 0) + 1;
        if (p === "fillText") texts.push(String(a[0]));
      };
    },
    set: (_, p: string, v) => ((store[p] = v), true),
  }) as unknown as CanvasRenderingContext2D;
  return { cx, texts, calls };
}

const frame = (over: Partial<Frame> = {}, mode: "terminal" | "working" = "terminal"): Frame => {
  const inp = input(mode), scene = layoutOrbit(inp);
  return {
    scene, input: inp, k: 0.6, zs: 1, clock: 10, hover: null, measure: "share", pace: "min", days: 7,
    arrivals: {}, offsets: new Map(), ...over,
  };
};

describe("arrivalDays", () => {
  it("groups the arrivals by source and sun, in days from the window's start, oldest first", () => {
    const now = 100 * DAY;
    const got = arrivalDays([{ source: "a", state: "done", at: now - 1 * DAY }, { source: "a", state: "done", at: now - 6 * DAY }, { source: "b", state: "archived", at: now - 3 * DAY }], now, 7 * DAY);
    expect(got.a.done).toEqual([1, 6]);
    expect(got.b.archived).toEqual([4]);
  });
});

describe("bottleneck", () => {
  it("is the working state a source spends most of its time in, none for a source with no time", () => {
    expect(bottleneck({ w: {}, src: { timeShare: { ready: 0.2, review: 0.6, waiting: 0.2 } } } as never)).toBe("review");
    expect(bottleneck({ w: {}, src: { timeShare: {} } } as never)).toBeNull();
  });
});

describe("hitOrbit", () => {
  it("finds the sun, then the source, under a point, within a margin of the body", () => {
    const f = frame(), { scene } = f;
    scene.sources[0].x = 50; scene.sources[0].y = 60;
    const sun = scene.suns[0];
    expect(hitOrbit(scene, sun.x + sun.r + 10, sun.y)).toEqual({ kind: "sun", u: sun });
    expect(hitOrbit(scene, 50, 60)).toEqual({ kind: "source", b: scene.sources[0] });
    expect(hitOrbit(scene, -9999, -9999)).toBeNull();
  });

  it("hits the terminal column's bodies when the suns are the working states", () => {
    const { scene } = frame({}, "working");
    expect(hitOrbit(scene, scene.ends[1].x, scene.ends[1].y)).toEqual({ kind: "sun", u: scene.ends[1] });
  });
});

describe("drawOrbit", () => {
  it.each(["terminal", "working"] as const)("names every sun, end and source with %s suns, and draws nothing that throws", (mode) => {
    const f = frame({}, mode), { cx, texts } = recorder();
    drawOrbit(cx, f);
    for (const s of [...f.scene.suns, ...f.scene.ends]) expect(texts).toContain(s.name);
    for (const b of f.scene.sources) expect(texts).toContain(b.name);
    expect(texts.some((t) => t.startsWith("replay · day"))).toBe(true);
  });

  it.each(["terminal", "working"] as const)("draws only the bodies, their names and a short tail at rest with %s suns", (mode) => {
    const f = frame({}, mode), { cx, texts, calls } = recorder();
    drawOrbit(cx, f);
    const suns = new Set([...f.scene.suns, ...f.scene.ends]).size, sources = f.scene.sources.length;
    // a disc is a fill and an outline, a planet adds its centre dot: no glow, share ring or moon
    expect(calls.arc).toBe(2 * suns + 3 * sources);
    // each source's orbit and its tail of TAIL segments
    expect(calls.moveTo).toBe(sources * (1 + TAIL));
    expect(texts.filter((t) => /ended here|task-days here|% /.test(t))).toEqual([]);
  });

  it("adds a hovered source's share ring and its trace to each sun, and leaves its numbers to the tip", () => {
    const f = frame(), b = f.scene.sources[0], rest = recorder(), { cx, texts, calls } = recorder();
    drawOrbit(rest.cx, f);
    drawOrbit(cx, { ...f, hover: { kind: "source", b } });
    expect(calls.arc).toBe(rest.calls.arc! + Object.keys(b.src.terminalShare).length);
    expect(calls.setLineDash).toBeGreaterThan(rest.calls.setLineDash!);
    expect(texts).toEqual(rest.texts);
  });

  it("traces a hovered sun to each source and draws no more text", () => {
    const f = frame(), u = f.scene.suns[0], rest = recorder(), { cx, texts } = recorder();
    drawOrbit(rest.cx, f);
    drawOrbit(cx, { ...f, hover: { kind: "sun", u } });
    expect(texts).toEqual(rest.texts);
  });

  it("rings a focused source and keeps its traces and share ring after the pointer leaves", () => {
    const f = frame(), b = f.scene.sources[0], hovered = recorder(), { cx, texts, calls } = recorder();
    drawOrbit(hovered.cx, { ...f, hover: { kind: "source", b } });
    drawOrbit(cx, { ...f, focus: { kind: "source", b } });
    expect(calls.arc).toBe(hovered.calls.arc! + 1);
    expect(calls.setLineDash).toBe(hovered.calls.setLineDash);
    expect(texts).toEqual(hovered.texts);
  });

  it("rings a focused sun, and draws the body under the pointer over a focus elsewhere", () => {
    const f = frame(), u = f.scene.suns[0], b = f.scene.sources[1], rest = recorder(), sun = recorder(), both = recorder(), hovered = recorder();
    drawOrbit(rest.cx, f);
    drawOrbit(sun.cx, { ...f, focus: { kind: "sun", u } });
    expect(sun.calls.arc).toBe(rest.calls.arc! + 1);
    drawOrbit(hovered.cx, { ...f, hover: { kind: "source", b } });
    drawOrbit(both.cx, { ...f, hover: { kind: "source", b }, focus: { kind: "sun", u } });
    expect(both.calls.arc).toBe(hovered.calls.arc! + 1);
  });

  it("sends a comet for an arrival that is in flight, and none a moment before it leaves", () => {
    // a quantum of one at 1 day a minute: the arrival at day 2 flies for 1.6 s, so half way is 0.8 s past day 2
    const arrivals = { alpha: { done: [2] } };
    const at = (clock: number) => {
      const r = recorder();
      drawOrbit(r.cx, frame({ arrivals, clock }));
      return r.calls.arc ?? 0;
    };
    expect(at(2 * 60 + 0.8)).toBeGreaterThan(at(2 * 60 - 5));
  });

  it("keeps an eased offset for each source's label", () => {
    const f = frame(), { cx } = recorder();
    drawOrbit(cx, f);
    expect([...f.offsets.keys()].sort()).toEqual(["alpha", "beta", "unattributed"]);
  });
});

describe("describeHover", () => {
  it("tells a terminal sun's ended runs by source, and a working sun's task-days and each source's time there", () => {
    const t = frame(), sun = t.scene.suns[0];
    expect(describeHover({ kind: "sun", u: sun }, t)).toMatchObject({ kind: "terminal · goal", name: "DONE", lines: ["14 runs ended here in 7 days"] });
    const w = frame({}, "working"), ready = w.scene.suns[0];
    const got = describeHover({ kind: "sun", u: ready }, w);
    expect(got).toMatchObject({ kind: "working state", lines: ["5 task-days spent here in 7 days"] });
    expect(got.chips.map((c) => c.text)).toEqual(["alpha 25% of its time", "beta 25% of its time", "unattributed 25% of its time"]);
  });

  it("tells a source's runs and its bottleneck, and marks the unattributed aggregate, with no Board to send a click to", () => {
    const f = frame(), [alpha, , un] = f.scene.sources;
    const a = describeHover({ kind: "source", b: alpha }, f);
    expect(a.kind).toBe("source");
    expect(a.lines[0]).toContain("10 runs ended");
    expect(a.lines[1]).toBe("bottleneck: IN_PROGRESS");
    expect(a.chips.map((c) => c.text)).toEqual(["DONE 70%", "ARCHIVED 30%"]);
    expect(describeHover({ kind: "source", b: un }, f).kind).toBe("source · unattributed");
  });
});
