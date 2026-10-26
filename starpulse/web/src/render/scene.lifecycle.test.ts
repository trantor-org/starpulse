import { describe, expect, it } from "vitest";
import { build, clip, textW, type Scene } from "./scene";
import { dag, machine, SAVED_STATES, savedBoardSky } from "../tests/sceneFixtures";
import type { Snapshot } from "../api";

describe("a Board whose every open state opens into lifecycle machines", () => {
  const ALL = SAVED_STATES.filter((id) => id !== "completed" && id !== "archived");
  /** Every open state opens into `n` machines, the primary and the rest each holding a sub-state that opens a child machine, with tasks working them. */
  const everyState = (n: number, tasks = 4, W = 1920, H = 1080, OPEN = ALL, short = false, dags = false) => savedBoardSky(W, H, (snap) => {
    const board = snap.flows[0], flows: Snapshot["flows"] = [];
    // the live Board's DAGs: long names writing the paths beside crowded states, three folded on one path, and ten free in the hangar
    if (dags) {
      const writes: Record<string, string[]> = { waiting_ready: ["dagu/board-dependency-reconciliation"], ready_in_progress: ["dagu/board-scheduler"], done_completed: ["dagu/backlog-sweep"], review_done: ["dagu/main-follow", "dagu/apply-merged", "dagu/pr-reaper"] };
      const free = { Ops: ["a", "b", "c", "d", "e", "f"].map((x) => `dagu/ops-${x}`), Docs: ["a", "b", "c", "d"].map((x) => `dagu/docs-${x}`) }, tied = Object.values(writes).flat();
      board.machine.writers = Object.fromEntries(Object.entries(writes).map(([e, ns]) => [e, ns.map((actor) => ({ actor, trigger: "dagu" }))]));
      snap.dags = [...tied, ...Object.values(free).flat()].map((d) => dag(d, [["run", []]]));
      snap.domains = [{ name: "Board", dags: tied.map((name) => ({ name, runSafe: false })) }, ...Object.entries(free).map(([name, ds]) => ({ name, dags: ds.map((d) => ({ name: d, runSafe: false })) }))];
    }
    board.agents = OPEN.flatMap((state) => Array.from({ length: tasks }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
    board.machine.submachines = OPEN.flatMap((state) => Array.from({ length: n }, (_, i) => {
      const name = short ? `${state.slice(0, 2)}${i}` : `${state}-machine-${String(i).padStart(2, "0")}`;
      flows.push({ name, agents: board.agents.filter((a) => a.state === state && i === 0).map((a, j) => ({ id: `${a.id}-s`, title: "t", state: "reading", model: "", task: a.id, active: 900 + j })), machine: machine(["reading", "writing"], short ? {} : { submachines: [{ state: "reading", machine: "child", exits: {}, parent: name, when: "it reads" }] }) });
      return { state, machine: name, exits: {}, parent: "board", when: "" };
    }));
    flows.push({ name: "child", agents: [], machine: machine(["a", "b"]) });
    snap.flows.push(...flows);
    snap.graphs.push(...flows.map((f) => f.name));
  });
  const boxes = (scene: Scene, W: number) => {
    const F = ((scene.labelScale ?? 1) * scene.w) / (0.94 * W), at = (id: string) => ({ x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity, id });
    const out = Object.fromEntries(Object.keys(scene.galaxies).map((id) => [id, at(id)])), grow = (id: string, x0: number, x1: number, y0: number, y1: number) => {
      const b = out[id];
      b.x0 = Math.min(b.x0, x0); b.x1 = Math.max(b.x1, x1); b.y0 = Math.min(b.y0, y0); b.y1 = Math.max(b.y1, y1);
    };
    for (const g of Object.values(scene.galaxies)) grow(g.id, g.x - g.R, g.x + g.R, g.y - g.R, g.y + g.R);
    for (const t of scene.tasks) grow(t.state, t.x - t.R, t.x + t.R, t.y - t.R, t.y + t.R);
    for (const m of scene.moons) {
      const sg = m.x < m.parent.x ? -1 : 1, end = m.x + sg * (m.R + m.ext + 10 + textW(scene.clipped ? clip(m.label) : m.label, 10.5) * F);
      grow(m.parent.id, Math.min(m.x - m.R, end), Math.max(m.x + m.R, end), m.y - m.R, m.y + m.R);
    }
    return Object.values(out);
  };

  // the first two checks read the same Board at each size: it is laid out once, and the scene is only read
  const laid = new Map<string, Scene>();
  const crowded = (n: number, W: number) => {
    const key = `${n}x${W}`;
    if (!laid.has(key)) laid.set(key, build(everyState(n, 4, W, 1080, ALL), { kind: "board" }));
    return laid.get(key)!;
  };

  it.each([[12, 1920], [20, 1920], [12, 1420], [20, 1420]])("holds 16 px between one state's tasks, moons and moon names and the next state's, at %i machines a state on a %i px canvas", (n, W) => {
    const scene = crowded(n, W), bs = boxes(scene, W), short: string[] = [];
    const px = (16 * scene.w) / (0.94 * W);
    for (const a of bs) for (const b of bs) if (a.id < b.id && Math.max(b.x0 - a.x1, a.x0 - b.x1, b.y0 - a.y1, a.y0 - b.y1) < px - 1e-6) short.push(`${a.id}/${b.id}`);

    expect(short).toEqual([]);
  });

  it.each([[12, 1920], [20, 1920], [12, 1420], [20, 1420]])("keeps every state, task, moon and moon name inside the fitted sky at %i machines a state on a %i px canvas", (n, W) => {
    const scene = crowded(n, W), bs = boxes(scene, W);

    expect(scene.w / scene.h).toBeCloseTo(W / 1080, 1);
    for (const b of bs) expect([b.id, b.x0 >= 0, b.x1 <= scene.w, b.y0 >= 0, b.y1 <= scene.h]).toEqual([b.id, true, true, true, true]);
  });

  /** Every state's disc, name and count line and moon rows, each as a box. */
  const labels = (scene: Scene, W: number) => {
    const F = ((scene.labelScale ?? 1) * scene.w) / (0.94 * W), out: { o: string; x0: number; x1: number; y0: number; y1: number }[] = [];
    const add = (o: string, x: number, hw: number, y0: number, y1: number) => out.push({ o, x0: x - hw, x1: x + hw, y0, y1 });
    for (const g of Object.values(scene.galaxies)) {
      for (const l of g.text) add(g.id, g.x, (textW(l.text, l.size) / 2) * F, g.y + (l.y - l.size / 2) * F, g.y + (l.y + l.size / 2) * F);
      add(g.id, g.x, g.R, g.y - g.R, g.y + g.R);
    }
    for (const m of scene.moons) {
      const sg = m.x < m.parent.x ? -1 : 1, end = m.x + sg * (m.R + m.ext + 10 + textW(scene.clipped ? clip(m.label) : m.label, 10.5) * F);
      out.push({ o: m.parent.id, x0: Math.min(m.x - m.R, end), x1: Math.max(m.x + m.R, end), y0: m.y - Math.max(m.R, 5.25 * F), y1: m.y + Math.max(m.R, 5.25 * F) });
    }
    return out;
  };

  it.each([[12, 1920], [20, 1920], [12, 1420], [20, 1420]])("keeps state names off each other and off every other state's rows at %i machines a state on a %i px canvas", (n, W) => {
    const scene = build(everyState(n, 4, W, 1080, ALL, false, true), { kind: "board" }), bs = labels(scene, W), hit: string[] = [];
    bs.forEach((a, i) => bs.slice(i + 1).forEach((b) => { if (a.o !== b.o && a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1) hit.push(`${a.o}/${b.o}`); }));

    expect(hit).toEqual([]);
  });
});
