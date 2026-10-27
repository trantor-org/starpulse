import { describe, expect, it } from "vitest";
import { build, Drawn, pickRows, SUN_FIT, SUN_R, sunTexts, tally, routed, curveDist, glyph, nearestWithin, paged, rings, sample, stateR, terminal, textW, turnPage, type Curve, type Galaxy, type MState, type Pt, type Scene } from "./scene";
import { ledgerLevel, type Level } from "./levels";
import { merge, midnight, Moves } from "./sky";
import { emptyNote } from "../features/level/machineRows";
import type { Cue, LedgerRow, Machine, Snapshot } from "../api";
import { dag, machine, SAVED_STATES, savedBoardSky } from "../tests/sceneFixtures";

const sky = () => {
  const snap: Snapshot = {
    graphs: ["board", "in-progress", "triaging-cr-reviews", "runs"],
    flows: [
      { name: "board", agents: [{ id: "PROJ-1", title: "t", state: "ready", model: "", labels: [] }], machine: machine(["ready", "in_progress", "review"], {
        transitions: [{ source: "ready", target: "in_progress", event: "CLAIM" }, { source: "in_progress", target: "review", event: "REVIEW" }],
        submachines: [{ state: "in_progress", machine: "in-progress", exits: {}, parent: "board", when: "" }],
        writers: { CLAIM: [{ actor: "board-scheduler", trigger: "dagu" }] },
      }) },
      { name: "in-progress", agents: [], machine: machine(["worktree_ready", "pr_opened"], {
        transitions: [{ source: "worktree_ready", target: "pr_opened", event: "PR_OPENED" }],
        submachines: [{ state: "pr_opened", machine: "triaging-cr-reviews", exits: {}, parent: "in-progress", when: "a PR is open" }],
      }) },
      { name: "triaging-cr-reviews", agents: [], machine: machine(["fetch", "reply"]) },
    ],
    dags: [dag("board-scheduler", [["claim", []]]), dag("worktree-reap", [["list", []], ["reap", ["list"]]])],
    domains: [{ name: "Board", dags: [{ name: "board-scheduler", runSafe: false }, { name: "worktree-reap", runSafe: true }] }],
    settled: {}, error: null, now: 1000,
  };
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W: 1670, H: 1080, T: 1000 };
};

describe("a terminal state", () => {
  const state = (id: string, final: boolean, flow?: string) => ({ id, final, flow });
  it("is a final state of the Board, where a task's lifecycle ends, and nothing else", () => {
    expect(terminal(state("completed", true))).toBe(true);
    expect(terminal(state("archived", true))).toBe(true);
    // Done is not final: the sweep moves its tasks on to Completed
    expect(terminal(state("done", false))).toBe(false);
    expect(terminal(state("review", false))).toBe(false);
  });
  it("is never a nested machine's final state, which hands its task back to the lifecycle", () => {
    expect(terminal(state("review_recorded", true, "in-progress"))).toBe(false);
    expect(terminal(state("needs_attention", true, "in-progress"))).toBe(false);
  });
});

describe("a machine's final state", () => {
  const st = (final: boolean, mini?: boolean): MState => ({ id: "s", name: "S", final, initial: false, machine: "f", n: 4, color: "#fff", mini, loops: [], x: 0, y: 0 });
  it("is the size of any other state with as many tasks, at the machine level and inside a machine planet", () => {
    expect(stateR(st(true))).toBe(stateR(st(false)));
    expect(stateR(st(true, true))).toBe(stateR(st(false, true)));
  });
  it("grows with its tasks up to a fixed maximum, so a state with thousands of tasks still fits its level", () => {
    const at = (n: number, final: boolean, mini?: boolean) => stateR({ ...st(final, mini), n });
    for (const [final, mini] of [[false, false], [true, false], [false, true], [true, true]] as const) {
      expect(at(0, final, mini)).toBeLessThan(at(25, final, mini));
      expect(at(10_000, final, mini)).toBe(at(1_000_000, final, mini));
    }
  });
});

describe("a DAG's glyph", () => {
  it("lays its steps out by dependency depth", () => {
    const g = glyph(dag("d", [["a", []], ["b", ["a"]], ["c", ["a"]]]));

    expect(g.nodes.map((n) => [n.name, n.x, n.y])).toEqual([["a", -14, 0], ["b", 14, -9], ["c", 14, 9]]);
    expect([g.w, g.h, g.links.length]).toEqual([28, 18, 2]);
  });

  it("draws steps that wait on each other in a cycle instead of hanging the page", () => {
    expect(glyph(dag("d", [["a", ["b"]], ["b", ["a"]]])).nodes).toHaveLength(2);
  });
});

describe("the orbit rings", () => {
  it("adds a ring further out once the last one is full", () => {
    expect(rings(20, 40, 11, 12).radii).toEqual([40]);
    expect(rings(30, 40, 11, 12).radii).toEqual([40, 52]);
  });
});

describe("machine paging", () => {
  const machines = Array.from({ length: 25 }, (_, i) => `skill-${i}`);

  it("wraps back from page one to the last page and forward from the last page to page one", () => {
    const [back] = paged("in_progress", machines, 0).pagers, [, forward] = paged("in_progress", machines, -1).pagers;

    expect([turnPage(back), turnPage(forward)]).toEqual([2, 0]);
  });

  it("splits the hidden machines between a back and a forward node, each holding those its turn reaches sooner", () => {
    const [back, forward] = paged("in_progress", machines, 0).pagers;

    expect([back.d, back.title, back.hidden]).toEqual([-1, "‹ 3/3", ["skill-24"]]);
    expect([forward.d, forward.title, forward.hidden]).toEqual([1, "2/3 ›", machines.slice(12, 24)]);
  });
});

/**
 * A Board with its axis (New to Done), three events and a self-transition, and one DAG per case. `writes` names the events each DAG writes,
 * `cues` the DAGs that run beside an event, `launches` DAGs that launch a machine inside In Progress and `free` the DAGs of other domains.
 */
const boardSky = ({ writes = {}, cues = [], launches = [], free = {}, ledgers, mergePins }: { writes?: Record<string, string[]>; cues?: Cue[]; launches?: string[]; free?: Record<string, string[]>; ledgers?: Record<string, LedgerRow[]>; mergePins?: LedgerRow[] } = {}) => {
  const writers: Record<string, { actor: string; trigger: string }[]> = {};
  for (const [name, events] of Object.entries(writes)) for (const e of events) (writers[e] ||= []).push({ actor: name, trigger: "dagu" });
  const tied = [...new Set([...Object.keys(writes), ...cues.map((c) => c.dag), ...launches])], loose = Object.values(free).flat();
  const snap: Snapshot = {
    graphs: ["board", "in-progress", "runs"],
    flows: [
      { name: "board", agents: [], machine: machine(["new", "ready", "in_progress", "review", "done"], {
        transitions: [
          { source: "ready", target: "in_progress", event: "CLAIM" }, { source: "in_progress", target: "review", event: "REVIEW" },
          { source: "review", target: "done", event: "MERGED" }, { source: "in_progress", target: "in_progress", event: "STAY" },
        ],
        submachines: [{ state: "in_progress", machine: "in-progress", exits: {}, parent: "board", when: "" }],
        launches: Object.fromEntries(launches.map((d) => [d, { skill: "delivering", machine: "in-progress" }])),
        writers, dagActors: Object.keys(writes), mainLine: ["new", "ready", "in_progress", "review", "done"],
      }) },
      { name: "in-progress", agents: [], machine: machine(["worktree_ready", "pr_opened"]) },
    ],
    dags: [...tied, ...loose].map((n) => dag(n, [["run", []]])),
    domains: [{ name: "Board", dags: tied.map((name) => ({ name, runSafe: false })) }, ...Object.entries(free).map(([name, dags]) => ({ name, dags: dags.map((d) => ({ name: d, runSafe: false })) }))],
    cues, mergePins, settled: {}, error: null, now: 1000,
  };
  const S = { ...merge(snap), ledgers: ledgers ?? {} }, moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W: 1920, H: 1080, T: 1000 };
};
/** `sky` with `counts[state]` more Board tasks in each named state. */
const withTasks = (sky: ReturnType<typeof boardSky>, counts: Record<string, number>) => {
  for (const [state, n] of Object.entries(counts))
    for (let i = 0; i < n; i++) sky.S.flows.board.agents.push({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] });
  return sky;
};
const cue = (dagName: string, event: string, state: string): Cue => ({ dag: dagName, event, state, on: "each merge" });
const edgeOf = (scene: Scene, event: string) => scene.bEdges.find((e) => e.event === event)!;

describe("a starting or terminal Board state", () => {
  const today = () => {
    const sky = boardSky();
    sky.S.flows.board.machine.states.find((s) => s.id === "done")!.final = true;
    const dot = (id: string, state: string) => ({ id, title: id, state, model: "", today: true });
    sky.S.today = { new: [dot("PROJ-1", "new"), dot("PROJ-2", "new")], done: [dot("PROJ-3", "done"), dot("PROJ-4", "done"), dot("PROJ-5", "done")] };
    return sky;
  };
  it("counts the day's arrivals on the Board and says so, orbiting those that settled on a terminal state", () => {
    const scene = build(today(), { kind: "board" }), on = (id: string) => scene.tasks.filter((k) => k.today && k.host === scene.galaxies[id]).map((k) => k.id);

    expect([scene.galaxies.new.n, scene.galaxies.done.n, scene.galaxies.review.n]).toEqual([2, 3, 0]);
    expect([scene.galaxies.new.today, scene.galaxies.done.today, scene.galaxies.review.today]).toEqual([2, 3, undefined]);
    expect(on("done")).toEqual(["PROJ-3", "PROJ-4", "PROJ-5"]);
  });
  it("orbits no arrival on a starting state, since each is drawn where it is now, yet counts them", () => {
    const sky = today(), scene = build(sky, { kind: "board" }), sun = build(sky, { kind: "state", id: "new" });

    expect([scene.tasks.filter((k) => k.host === scene.galaxies.new).length, sun.tasks.length]).toEqual([0, 0]);
    expect([sun.sun!.n, sun.sun!.today]).toEqual([2, 2]);
  });
  it("draws no task on a starting state, not even one in its lane, and counts only the day's arrivals; a terminal state keeps its tasks and adds the day's", () => {
    const sky = today();
    sky.S.flows.board.agents.push(
      { id: "PROJ-1", title: "PROJ-1", state: "new", model: "" },
      { id: "PROJ-7", title: "PROJ-7", state: "new", model: "" }, // in the lane, not created today
      { id: "PROJ-6", title: "PROJ-6", state: "done", model: "" },
    );
    const board = build(sky, { kind: "board" }), sun = build(sky, { kind: "state", id: "new" });
    const on = (id: string) => board.tasks.filter((k) => k.host === board.galaxies[id]).map((k) => k.id).sort();

    expect([on("new"), on("done")]).toEqual([[], ["PROJ-3", "PROJ-4", "PROJ-5", "PROJ-6"]]);
    expect([board.galaxies.new.n, board.galaxies.new.today, board.galaxies.done.n, board.galaxies.done.today]).toEqual([2, 2, 4, 3]);
    expect([sun.sun!.n, sun.sun!.today, sun.tasks.map((k) => k.id)]).toEqual([2, 2, []]);
  });
  it("keeps a task on a terminal state until local midnight after it entered it, and one the server gave no time for", () => {
    // local noon: 13 hours back is yesterday, inside a rolling day
    const sky = today(), now = midnight(new Date(2026, 9, 10)) + 12 * 3600;
    sky.S.now = now;
    sky.S.flows.board.agents.push(
      { id: "PROJ-6", title: "PROJ-6", state: "done", model: "", entered: now - 13 * 3600 },
      { id: "PROJ-8", title: "PROJ-8", state: "done", model: "", entered: now - 11 * 3600 },
      { id: "PROJ-9", title: "PROJ-9", state: "done", model: "" },
      { id: "PROJ-10", title: "PROJ-10", state: "review", model: "", entered: now - 13 * 3600 },
    );
    const board = build(sky, { kind: "board" }), sun = build(sky, { kind: "state", id: "done" });
    const on = (id: string) => board.tasks.filter((k) => k.host === board.galaxies[id]).map((k) => k.id).sort();
    const kept = ["PROJ-3", "PROJ-4", "PROJ-5", "PROJ-8", "PROJ-9"];

    expect([on("done"), on("review")]).toEqual([kept, ["PROJ-10"]]);
    expect([board.galaxies.done.n, board.galaxies.done.today, sun.sun!.n]).toEqual([5, 3, 5]);
    expect(sun.tasks.map((k) => k.id).sort()).toEqual(kept);
  });
  it("counts and orbits them on a terminal state's own level too", () => {
    const sun = build(today(), { kind: "state", id: "done" });

    expect([sun.sun!.n, sun.sun!.today, sun.tasks.map((k) => k.id)]).toEqual([3, 3, ["PROJ-3", "PROJ-4", "PROJ-5"]]);
  });
});

describe("a Board state's task rings", () => {
  const withDone = (n: number) => {
    const sky = boardSky();
    sky.S.flows.board.machine.states.find((s) => s.id === "done")!.final = true;
    sky.S.today = { done: Array.from({ length: n }, (_, i) => ({ id: `PROJ-${i}`, title: "t", state: "done", model: "", today: true })) };
    return build(sky, { kind: "board" });
  };
  it("spreads a crowded state's tasks over a wider band, so no two dots or rings sit closer than a pointer can tell apart (TASK-8741)", () => {
    const scene = withDone(376), done = scene.tasks.filter((k) => k.host === scene.galaxies.done), radii = scene.galaxies.done.rings!;
    const perRing = radii.map((R) => done.filter((k) => k.R === R).length);

    expect(done).toHaveLength(376);
    radii.slice(1).forEach((R, i) => expect(R - radii[i]).toBeGreaterThanOrEqual(8 - 1e-9));
    radii.forEach((R, i) => expect((2 * Math.PI * R) / perRing[i]).toBeGreaterThanOrEqual(8));
  });
  it("keeps a quiet state's footprint, its tasks on the one ring nearest the sun", () => {
    const quiet = withDone(5), busy = withDone(376);

    const r = quiet.galaxies.done.r;

    expect(quiet.galaxies.done.rings).toEqual([r + 14]);
    expect(quiet.galaxies.done.R).toBe(r + 44);
    expect(busy.galaxies.done.R).toBeGreaterThan(busy.galaxies.done.r + 44);
  });
});

describe("a Board state's sun", () => {
  it("carries the state's final flag, so a terminal state's level draws a black hole rather than a sun", () => {
    const sky = boardSky();
    sky.S.flows.board.machine.states.find((s) => s.id === "done")!.final = true;
    expect(build(sky, { kind: "state", id: "done" }).sun!.final).toBe(true);
    expect(build(sky, { kind: "state", id: "review" }).sun!.final).toBe(false);
  });
});

describe("a Board laid out at the values it shows", () => {
  it("lays a Board out the same whichever Board was laid before it, so a remembered zoom never leaks between inputs", () => {
    const quiet = withTasks(boardSky(), { ready: 2 }), busy = withTasks(boardSky(), { ready: 150, done: 400 });
    const at = (s: Scene) => Object.fromEntries(Object.entries(s.galaxies).map(([id, g]) => [id, [g.x, g.y, g.r]]));
    const first = at(build(busy, { kind: "board" })), other = at(build(quiet, { kind: "board" }));

    expect(at(build(busy, { kind: "board" }))).toEqual(first);
    expect(at(build(quiet, { kind: "board" }))).toEqual(other);
    expect(other).not.toEqual(first);
  });
  it("carries each state's place, and the sky's width, as the renderer eases them", () => {
    const sky = withTasks(boardSky(), { ready: 150, done: 400 }), full = build(sky, { kind: "board" });
    const shown = build({ ...sky, ease: (key: string, v: number) => (key.endsWith(".r") ? v / 2 : key === "done.x" ? v + 100 : key === "sky.w" ? v + 50 : v) }, { kind: "board" });

    expect(shown.galaxies.done.x).toBeCloseTo(full.galaxies.done.x + 100);
    expect(shown.w).toBeCloseTo(full.w + 50);
  });
  it("eases each state's footprint and where its paths end, so a new ring of tasks moves the ends instead of snapping them", () => {
    const sky = withTasks(boardSky(), { ready: 150, done: 400 }), full = build(sky, { kind: "board" });
    const shown = build({ ...sky, ease: (key: string, v: number) => (key.endsWith(".R") || key.endsWith(".edge") ? v + 30 : v) }, { kind: "board" });

    for (const id of Object.keys(full.galaxies)) expect(shown.galaxies[id].R).toBeCloseTo(full.galaxies[id].R + 30);
    for (const id of Object.keys(full.galaxies)) expect(shown.galaxies[id].edge).toBeCloseTo(full.galaxies[id].edge + 30);
  });
  it("places its states from their true sizes, so an eased radius never moves another state's target", () => {
    const sky = withTasks(boardSky(), { ready: 150, done: 400 }), full = build(sky, { kind: "board" });
    const shrunk = build({ ...sky, ease: (key: string, v: number) => (key.endsWith(".r") ? v / 2 : v) }, { kind: "board" });

    for (const id of Object.keys(full.galaxies)) expect([shrunk.galaxies[id].x, shrunk.galaxies[id].y]).toEqual([full.galaxies[id].x, full.galaxies[id].y]);
    expect(shrunk.w).toBe(full.w);
  });
  it("eases each path's bend in its two states' own frame, so the path rides its states and its ends stay on their rims", () => {
    const sky = withTasks(boardSky(), { ready: 150, done: 400 }), full = build(sky, { kind: "board" });
    const bent = build({ ...sky, ease: (key: string, v: number) => (key.endsWith(".v") ? v + 0.2 : v) }, { kind: "board" });
    const paths = (s: typeof full) => s.bEdges.filter((e) => !e.loop) as unknown as (Curve & { source: string; target: string })[];

    for (const [e, f] of paths(bent).map((e, i) => [e, paths(full)[i]] as const)) {
      const a = bent.galaxies[e.source], b = bent.galaxies[e.target], dx = b.x - a.x, dy = b.y - a.y;
      expect([e.c.x, e.c.y]).toEqual([expect.closeTo(f.c.x - 0.2 * dy, 6), expect.closeTo(f.c.y + 0.2 * dx, 6)]);
      expect(Math.hypot(e.p0.x - a.x, e.p0.y - a.y)).toBeCloseTo(a.edge, 6);
      expect(Math.hypot(e.p1.x - b.x, e.p1.y - b.y)).toBeCloseTo(b.edge, 6);
    }
  });
});

describe("a Board path's route", () => {
  // New and Done on one row with Ready between them, so the straight path from New to Done runs through Ready
  const at = (id: string, x: number, y: number, R: number) => ({ id, x, y, R, edge: R }) as unknown as Parameters<typeof routed>[0];
  const sky = { x: 800, y: 600 }, a = at("new", 100, 300, 30), b = at("done", 700, 300, 30), c0 = { x: 400, y: 300 };

  it("keeps the bend it held while that bend still clears, rather than hopping to another spot the search would pick", () => {
    const o = at("ready", 400, 300, 40), first = routed(a, b, c0, [a, b, o], new Drawn(), sky);
    const held = { x: first.c.x, y: 600 - first.c.y }; // the same bend on the other side clears as well

    expect(routed(a, b, c0, [a, b, o], new Drawn(), sky, held).c).toEqual(held);
  });
  it("is held from one Board to the next through the bends the renderer keeps, each in the frame of its two states", () => {
    // Ready → Done runs down the one tier through In progress and Review, so it bends round them
    const sky = withTasks(boardSky(), { ready: 150, done: 400 }), routes = new Map<string, Pt>();
    sky.S.flows.board.machine.tiers = [["ready", "in_progress", "review", "done"]];
    sky.S.flows.board.machine.transitions.push({ source: "ready", target: "done", event: "SKIP" });
    build({ ...sky, routes }, { kind: "board" });
    expect(routes.size).toBeGreaterThan(0);

    const [k, h] = [...routes][0], nudged = new Map([[k, { x: h.x, y: h.y + 0.01 }]]), [source, target] = k.split(">");
    const scene = build({ ...sky, routes: nudged }, { kind: "board" }), e = scene.bEdges.find((x) => x.source === source && x.target === target)!;
    const A = scene.galaxies[source], B = scene.galaxies[target], dx = B.x - A.x, dy = B.y - A.y;
    expect([e.c!.x, e.c!.y]).toEqual([expect.closeTo(A.x + h.x * dx - (h.y + 0.01) * dy, 6), expect.closeTo(A.y + h.x * dy + (h.y + 0.01) * dx, 6)]);
  });
  it("straightens a bent path only once the straight path clears by a margin, so a state's size crossing the line never flips it back and forth", () => {
    const held = { x: 400, y: 120 }, by = (gap: number) => at("ready", 400, 300 + 40 + 20 + gap, 40);

    expect(routed(a, b, c0, [a, b, by(4)], new Drawn(), sky).c).toEqual(c0);
    expect(routed(a, b, c0, [a, b, by(4)], new Drawn(), sky, held).c).toEqual(held);
    expect(routed(a, b, c0, [a, b, by(30)], new Drawn(), sky, held).c).toEqual(c0);
  });
  it("keeps the bend it held while a state growing toward it leaves three quarters of its clearance, so a ring of tasks filling never hops it", () => {
    const o = (R: number) => at("ready", 400, 300, R), first = routed(a, b, c0, [a, b, o(40)], new Drawn(), sky);
    const room = Math.min(...sample(first, 400).map((p) => Math.hypot(p.x - 400, p.y - 300))) - 40;

    expect(routed(a, b, c0, [a, b, o(40 + room - 16)], new Drawn(), sky, first.c).c).toEqual(first.c);
    expect(routed(a, b, c0, [a, b, o(40 + room - 12)], new Drawn(), sky, first.c).c).not.toEqual(first.c);
  });

  it("never cuts back through either of its own two states", () => {
    // a bend behind New starts the path on New's far side, to run back through New on its way to Done
    const behind = { x: 60, y: 300 }, e = routed(a, b, behind, [a, b], new Drawn(), sky);

    expect(e.c).not.toEqual(behind);
    for (const g of [a, b]) expect(Math.min(...sample(e, 400).map((p) => Math.hypot(p.x - g.x, p.y - g.y)))).toBeGreaterThan(g.edge - 2.5);
  });
  it("passes through a state's footprint, never through what the state draws, where no bend clears the footprint", () => {
    // Ready's footprint covers the whole sky, and it draws only the 40 px at its centre
    const o = { ...at("ready", 400, 300, 600), edge: 40 }, e = routed(a, b, c0, [a, b, o], new Drawn(), sky);

    expect(e.c).not.toEqual(c0);
    expect(Math.min(...sample(e, 400).map((p) => Math.hypot(p.x - o.x, p.y - o.y)))).toBeGreaterThan(40 + 9);
  });
  it("runs through what a state draws as shallowly as it can, where every path on the sky does", () => {
    // Ready draws a disc wider than the sky is tall, so no path on the sky clears it; the straight path runs through its centre, a bend only through its rim
    const o = { ...at("ready", 400, 300, 500), edge: 400 }, e = routed(a, b, c0, [a, b, o], new Drawn(), sky);

    expect(Math.min(...sample(e, 400).map((p) => Math.hypot(p.x - o.x, p.y - o.y)))).toBeGreaterThan(100);
  });
  it("bows its control point below the sky when the path itself stays on it and clears what a bend inside the sky cannot", () => {
    // Ready draws a disc half again the sky's height: a control point inside the sky bows the path only 150 px from its centre, one 900 px
    // down bows it to the sky's edge
    const o = { ...at("ready", 400, 300, 600), edge: 200 }, e = routed(a, b, c0, [a, b, o], new Drawn(), sky), s = sample(e, 400);

    expect(Math.min(...s.map((p) => Math.hypot(p.x - o.x, p.y - o.y)))).toBeGreaterThan(200 + 9);
    expect(Math.max(...s.map((p) => p.y))).toBeLessThanOrEqual(sky.y + 0.5);
  });

  it("bows its control point above the sky when the path itself stays on it and clears what a bend inside the sky cannot", () => {
    // Ready draws a disc low on the sky: a control point on the sky bows the path no higher than its top edge, one above the sky clears it
    const o = { ...at("ready", 400, 500, 400), edge: 250 }, l = at("new", 100, 500, 30), r = at("done", 700, 500, 30);
    const e = routed(l, r, c0, [l, r, o], new Drawn(), sky), s = sample(e, 400);

    expect(e.c.y).toBeLessThan(10);
    expect(Math.min(...s.map((p) => Math.hypot(p.x - o.x, p.y - o.y)))).toBeGreaterThan(250 + 9);
    expect(Math.min(...s.map((p) => p.y))).toBeGreaterThanOrEqual(10 - 0.5);
  });

  it("keeps a path that a bend on the sky already clears on the sky", () => {
    const o = { ...at("ready", 400, 300, 30), edge: 60 }, e = routed(a, b, c0, [a, b, o], new Drawn(), sky);

    expect(e.c.x).toBeGreaterThanOrEqual(10);
    expect(e.c.y).toBeGreaterThanOrEqual(10);
    expect(e.c.x).toBeLessThanOrEqual(sky.x - 10);
    expect(e.c.y).toBeLessThanOrEqual(sky.y - 10);
  });

  it("runs a reopened Waiting and Done pair around the states between them on a wide window, where no bend on the sky does", () => {
    // the Board's states as the live Board lays them out at 3440x1080 and at 2304x900: one band of In Progress and Review between the pair
    const wide = (spec: [string, number, number, number, number][]) => spec.map(([id, x, y, R, edge]) => ({ ...at(id, x, y, R), edge }));
    const boards: [string, ReturnType<typeof wide>, Pt, Pt][] = [
      ["3440x1080", wide([["new", 119, 310, 78, 44], ["ready", 358, 179, 78, 70], ["waiting", 358, 441, 78, 82], ["in_progress", 822, 458, 131, 109],
        ["review", 1367, 161, 131, 109], ["needs_attention", 596, 179, 78, 44], ["done", 1758, 179, 78, 82], ["archived", 1758, 441, 78, 58]]),
        { x: 1029, y: 156 }, { x: 1877, y: 549 }],
      ["2304x900", wide([["new", 87, 321, 78, 44], ["ready", 262, 186, 78, 70], ["waiting", 262, 456, 78, 82], ["in_progress", 611, 473, 131, 109],
        ["review", 1119, 168, 131, 109], ["needs_attention", 437, 186, 78, 44], ["done", 1460, 186, 78, 82], ["archived", 1460, 456, 78, 58]]),
        { x: 832, y: 189 }, { x: 1547, y: 564 }],
    ];
    const inside = boards.map(([name, gs, start, bounds]) => {
      const [from, to] = [gs.find((g) => g.id === "waiting")!, gs.find((g) => g.id === "done")!];
      const e = routed(from, to, start, gs, new Drawn(), bounds), s = sample(e, 200);
      return [name, gs.filter((g) => g !== from && g !== to && s.some((p) => Math.hypot(p.x - g.x, p.y - g.y) < g.edge)).map((g) => g.id),
        s.every((p) => p.x >= 10 - 0.5 && p.y >= 10 - 0.5 && p.x <= bounds.x + 0.5 && p.y <= bounds.y + 0.5)];
    });

    expect(inside).toEqual([["3440x1080", [], true], ["2304x900", [], true]]);
  });

  describe("searched for a Board's first snapshot", () => {
    const round = (n: number) => Math.round(n * 1e6) / 1e6;
    const routesOf = (sky: ReturnType<typeof savedBoardSky>) => build(sky, { kind: "board" }).bEdges.map((e) => `${e.source}>${e.target} ${round(e.c!.x)},${round(e.c!.y)}`);
    const crowd = (counts: Record<string, number>) => (snap: Snapshot) => {
      snap.flows[0].agents = Object.entries(counts).flatMap(([state, n]) => Array.from({ length: n }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
    };

    it("bends each blocked path to the same spot on the saved Board, empty and crowded, at each window size", () => {
      const sizes: [number, number][] = [[1920, 1080], [1280, 720]];
      const routes = Object.fromEntries(sizes.flatMap(([W, H]) => [
        [`${W}x${H}`, routesOf(savedBoardSky(W, H))],
        [`${W}x${H} crowded`, routesOf(savedBoardSky(W, H, crowd({ ready: 90, waiting: 60, in_progress: 40, done: 90, review: 20 })))],
      ]));
      expect(routes).toMatchInlineSnapshot(`
        {
          "1280x720": [
            "new>ready 152.524766,350.060482",
            "new>blocked 255.85884,296.270071",
            "new>waiting 250,370",
            "new>in_progress 330,330",
            "ready>in_progress 530,490",
            "ready>blocked 293.656643,422.494063",
            "ready>waiting 294.583598,571.328444",
            "ready>archived 290,170",
            "blocked>ready 293.656643,422.494063",
            "blocked>in_progress 569.043111,322.521017",
            "blocked>archived 570,250",
            "waiting>ready 294.583598,571.328444",
            "waiting>in_progress 547.184923,395.449136",
            "waiting>archived 530,650",
            "in_progress>blocked 569.043111,322.521017",
            "in_progress>review 713.880551,360.324842",
            "in_progress>done 801.343629,198.355468",
            "in_progress>needs_attention 552.540985,137.941344",
            "in_progress>archived 810,410",
            "review>done 863.540292,352.270697",
            "review>in_progress 713.880551,360.324842",
            "review>archived 857.840628,507.095405",
            "needs_attention>ready 305.490533,321.526425",
            "needs_attention>in_progress 552.540985,137.941344",
            "needs_attention>archived 490,370",
            "done>completed 1023.213838,201.701739",
          ],
          "1280x720 crowded": [
            "new>ready 152.524766,350.060482",
            "new>blocked 255.85884,296.270071",
            "new>waiting 250,370",
            "new>in_progress 330,330",
            "ready>in_progress 490,490",
            "ready>blocked 293.656643,422.494063",
            "ready>waiting 294.583598,571.328444",
            "ready>archived 330,170",
            "blocked>ready 293.656643,422.494063",
            "blocked>in_progress 569.043111,322.521017",
            "blocked>archived 610,250",
            "waiting>ready 294.583598,571.328444",
            "waiting>in_progress 547.184923,395.449136",
            "waiting>archived 570,650",
            "in_progress>blocked 569.043111,322.521017",
            "in_progress>review 713.880551,360.324842",
            "in_progress>done 801.343629,198.355468",
            "in_progress>needs_attention 552.540985,137.941344",
            "in_progress>archived 810,410",
            "review>done 863.540292,352.270697",
            "review>in_progress 713.880551,360.324842",
            "review>archived 890,490",
            "needs_attention>ready 305.490533,321.526425",
            "needs_attention>in_progress 552.540985,137.941344",
            "needs_attention>archived 490,330",
            "done>completed 1023.213838,201.701739",
          ],
          "1920x1080": [
            "new>ready 126.444246,291.06",
            "new>blocked 213.275944,244.017978",
            "new>waiting 213.275944,330.899185",
            "new>in_progress 330,250",
            "ready>in_progress 530,370",
            "ready>blocked 244.244283,349.562552",
            "ready>waiting 245.828907,474.649705",
            "ready>archived 290,130",
            "blocked>ready 244.244283,349.562552",
            "blocked>in_progress 470.907056,265.455748",
            "blocked>archived 610,250",
            "waiting>ready 245.828907,474.649705",
            "waiting>in_progress 450,370",
            "waiting>archived 450,530",
            "in_progress>blocked 470.907056,265.455748",
            "in_progress>review 587.459394,299.200948",
            "in_progress>done 661.284097,163.345872",
            "in_progress>needs_attention 457.846721,114.173746",
            "in_progress>archived 770,410",
            "review>done 712.02211,291.25229",
            "review>in_progress 587.459394,299.200948",
            "review>archived 707.201364,420.847235",
            "needs_attention>ready 254.593528,266.539348",
            "needs_attention>in_progress 457.846721,114.173746",
            "needs_attention>archived 490,330",
            "done>completed 848.237262,165.854697",
          ],
          "1920x1080 crowded": [
            "new>ready 126.444246,291.06",
            "new>blocked 213.275944,244.017978",
            "new>waiting 250,330",
            "new>in_progress 330,250",
            "ready>in_progress 490,370",
            "ready>blocked 244.244283,349.562552",
            "ready>waiting 245.828907,474.649705",
            "ready>archived 330,130",
            "blocked>ready 244.244283,349.562552",
            "blocked>in_progress 470.907056,265.455748",
            "blocked>archived 610,250",
            "waiting>ready 245.828907,474.649705",
            "waiting>in_progress 530,370",
            "waiting>archived 530,530",
            "in_progress>blocked 470.907056,265.455748",
            "in_progress>review 587.459394,299.200948",
            "in_progress>done 661.284097,163.345872",
            "in_progress>needs_attention 457.846721,114.173746",
            "in_progress>archived 730,370",
            "review>done 712.02211,291.25229",
            "review>in_progress 587.459394,299.200948",
            "review>archived 707.201364,420.847235",
            "needs_attention>ready 254.593528,266.539348",
            "needs_attention>in_progress 457.846721,114.173746",
            "needs_attention>archived 450,290",
            "done>completed 848.237262,165.854697",
          ],
        }
      `);
    });
    it("takes the spot first met on the search order when equally near spots tie, the lower y first", () => {
      // c0 sits on the 40 px lattice the search walks, so the spots above and below it are equally near and equally clear
      const from = at("new", 100, 290, 30), to = at("done", 700, 290, 30), o = at("ready", 410, 290, 40);
      const tied = routed(from, to, { x: 410, y: 290 }, [from, to, o], new Drawn(), sky);
      expect({ x: round(tied.c.x), y: round(tied.c.y) }).toMatchInlineSnapshot(`
        {
          "x": 410,
          "y": 170,
        }
      `);
    });
  });
});

describe("a Board path's route search", () => {
  // the search written plainly: every spot on the sky in order of bend, each one costed at every sample against every state
  const reference = (a: Galaxy, b: Galaxy, c0: Pt, all: Galaxy[], drawn: Drawn, sky: Pt, held?: Pt): Curve => {
    const others = all.filter((g) => g !== a && g !== b);
    const rim = (g: Galaxy, c: Pt) => {
      const t = Math.atan2(c.y - g.y, c.x - g.x);
      return { x: g.x + Math.cos(t) * g.edge, y: g.y + Math.sin(t) * g.edge };
    };
    const shape = (c: Pt): Curve => ({ p0: rim(a, c), c, p1: rim(b, c) });
    const at = ({ p0, c, p1 }: Curve, t: number) => ({ x: (1 - t) ** 2 * p0.x + 2 * (1 - t) * t * c.x + t * t * p1.x, y: (1 - t) ** 2 * p0.y + 2 * (1 - t) * t * c.y + t * t * p1.y });
    const points = (e: Curve, n: number) => Array.from({ length: n + 1 }, (_, i) => at(e, i / n));
    // what a path runs over: 50 for each state it crosses what is drawn of (its own two as well), up to 100 at the state's centre, 1 for each
    // footprint it passes within `by` of
    const over = (e: Curve, by = 20) => {
      const on = points(e, 48), d = (g: Galaxy) => Math.min(...on.map((p) => (p.x - g.x) ** 2 + (p.y - g.y) ** 2));
      const own = [a, b].some((g) => d(g) < (g.edge - 2) ** 2) ? 50 : 0;
      return others.reduce((n, g) => n + (d(g) < (g.edge + 10) ** 2 ? 50 * (2 - Math.sqrt(d(g)) / (g.edge + 10)) : d(g) < (g.R + by) ** 2 ? 1 : 0), own);
    };
    const crossings = (e: Curve) => points(e, 30).filter((p) => drawn.near(p.x, p.y)).length;
    const straight = shape(c0);
    if (!over(straight, held ? 36 : 20)) return straight;
    if (held && !over(shape(held), 15)) return shape(held);
    const spots: { c: Pt; bend: number }[] = [];
    for (let x = 10; x <= sky.x - 10; x += 40) for (let y = 10; y <= sky.y - 10; y += 40) spots.push({ c: { x, y }, bend: Math.hypot(x - c0.x, y - c0.y) / 200 });
    let best = straight, cost = over(straight) + 0.05 * crossings(straight);
    for (const { c, bend } of spots.sort((p, q) => p.bend - q.bend)) {
      const e = shape(c), total = bend + over(e) + 0.05 * crossings(e);
      if (total < cost) [cost, best] = [total, e];
    }
    return best;
  };
  // a seeded generator, so a failure names the case that broke
  const rand = (seed: number) => () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);

  it("picks the same path as a search that tries every spot against every state, so a faster search draws the same Board", () => {
    let searched = 0;
    for (let n = 0; n < 30; n++) {
      const r = rand(n + 1), sky = { x: 600 + r() * 400, y: 400 + r() * 200 };
      const gs = Array.from({ length: 4 + Math.floor(r() * 10) }, (_, i) => ({ id: `s${i}`, x: 60 + r() * (sky.x - 120), y: 60 + r() * (sky.y - 120), R: 12 + r() * 36 })).map((g) => ({ ...g, edge: g.R })) as unknown as Galaxy[];
      const [a, b] = gs, c0 = { x: (a.x + b.x) / 2 + (r() - 0.5) * 200, y: (a.y + b.y) / 2 + (r() - 0.5) * 200 };
      const drawn = new Drawn();
      drawn.add(Array.from({ length: 80 }, () => ({ x: r() * sky.x, y: r() * sky.y })));
      const held = n % 3 ? undefined : { x: r() * sky.x, y: r() * sky.y };

      const got = routed(a, b, c0, gs, drawn, sky, held);
      expect(got, `case ${n}`).toEqual(reference(a, b, c0, gs, drawn, sky, held));
      if (got.c !== c0 && got.c.x % 40 === 10) searched++;
    }
    expect(searched).toBeGreaterThanOrEqual(10); // a third of the cases ran the search rather than drawing straight or keeping their bend
  }, 60_000); // the brute-force reference takes ~3 s alone and passed 15 s on a loaded CI runner
});

describe("a Board with DAGs in its snapshot", () => {
  const loaded = () => {
    const sky = boardSky({ writes: { alpha: ["CLAIM"], beta: ["CLAIM", "MERGED"] }, cues: [cue("healthcheck", "MERGED", "done")], launches: ["pr-launcher"], free: { Ops: ["free-a", "free-b"] } });
    sky.S.writers.REVIEW = [{ actor: "operator", trigger: "ui" }];
    return sky;
  };

  it("draws no DAG body, fold, tether or group, whatever the DAGs write, are cued by or launch", () => {
    const scene = build(loaded(), { kind: "board" });

    expect([Object.keys(scene.stars), scene.groups]).toEqual([[], []]);
  });

  it("lays the Board out as it does with no DAG at all", () => {
    const at = (scene: Scene) => Object.values(scene.galaxies).map((g) => [g.id, g.x, g.y, g.r]);

    expect(at(build(loaded(), { kind: "board" }))).toEqual(at(build(boardSky(), { kind: "board" })));
  });

  it("keeps the states and the paths between them, and carries on them only the writers that are no DAG", () => {
    const scene = build(loaded(), { kind: "board" }), writers = (event: string) => edgeOf(scene, event).writers;

    expect(scene.bEdges.map((e) => e.event)).toEqual(build(boardSky(), { kind: "board" }).bEdges.map((e) => e.event));
    expect([writers("CLAIM"), writers("MERGED")]).toEqual([[], []]);
    expect(writers("REVIEW")).toEqual([{ actor: "operator", trigger: "ui", event: "REVIEW" }]);
  });
});

/** The distance from a point to the nearest sample of a path. */
const clearance = (e: Curve, g: Pt & { R: number }) => Math.min(...sample(e, 200).map((q) => Math.hypot(q.x - g.x, q.y - g.y))) - g.R;

/** The tiers the trantor Board declares: the states the Star Map draws at each stage, left to right. */
const DEFAULT_TIERS = [["new"], ["ready", "waiting"], ["needs_attention"], ["in_progress"], ["review"], ["done", "archived"]];

/** `n` machines open under `state`, each its own flow. */
const machinesOn = (state: string, n: number) => (snap: Snapshot) => {
  snap.flows[0].machine.submachines = Array.from({ length: n }, (_, i) => ({ state, machine: `m${i}`, exits: {}, parent: "board", when: "" }));
  for (let i = 0; i < n; i++) {
    snap.graphs.push(`m${i}`);
    snap.flows.push({ name: `m${i}`, agents: [], machine: machine(["a", "b"]) });
  }
};

/** Whether every line a sun draws sits inside its black hole's shadow, in the type the canvas draws; a sun that cannot grow draws none. */
const holds = (s: Scene) => {
  const F = s.labelScale! * s.px!;

  return Object.values(s.galaxies).every((g) => g.text.every((l) => Math.hypot(textW(l.text, l.size * F) / 2, Math.abs(l.y * F) + (l.size * F) / 2) <= g.r * SUN_FIT + 1e-6));
};

describe("the Board's tiers", () => {
  const tiered = (W: number, H: number, tiers: string[][] | undefined = DEFAULT_TIERS, patch: (snap: Snapshot) => void = () => {}, scale?: number) => {
    const sky = savedBoardSky(W, H, (snap) => {
      if (tiers) snap.flows[0].machine.tiers = tiers;
      patch(snap);
    });
    return build(scale ? { ...sky, scale } : sky, { kind: "board" });
  };
  /** The zoom the Board is drawn at: the canvas over the sky's width, less the 6% margin. */
  const zoom = (s: Scene, W: number) => (0.94 * W) / s.w;

  it("lays the states out left to right in tier order, a tier's states stacked in one cell", () => {
    const g = tiered(1920, 1080).galaxies;
    const heads = ["new", "ready", "needs_attention", "in_progress", "review", "done"];

    heads.slice(1).forEach((id, i) => expect(g[id].x).toBeGreaterThan(g[heads[i]].x));
    expect(g.waiting.x).toBeCloseTo(g.ready.x);
    expect(g.waiting.y).not.toBeCloseTo(g.ready.y);
    expect(g.archived.x).toBeCloseTo(g.done.x);
    expect(g.archived.y).not.toBeCloseTo(g.done.y);
  });

  describe("a state no tier names", () => {
    /** The Board with states of no tier, joined to the others by `paths` as source>target pairs. */
    const joined = (extra: string[], paths: string[]) =>
      tiered(1920, 1080, DEFAULT_TIERS, (snap) => {
        const m = snap.flows[0].machine;
        m.states = [...m.states, ...extra.map((id) => ({ id, name: id, initial: false, final: false }))];
        m.transitions = [...m.transitions, ...paths.map((p) => ({ source: p.split(">")[0], target: p.split(">")[1], event: p }))];
      }).galaxies;

    it("takes a tier of its own after them, in the machine's order, when no path joins it to a state a tier names", () => {
      const g = joined(["held", "parked"], []);

      expect(g.held.x).toBeGreaterThan(g.done.x);
      expect(g.parked.x).toBeGreaterThan(g.held.x);
    });

    // stacked in the tier at the mean of the tiers its paths join it to, or in a tier of its own right after it: whichever draws the sun larger
    it("is drawn in or beside the tier at the mean of the tiers its paths join, between two tiers when they are shared evenly", () => {
      const g = joined(["held"], ["ready>held", "held>in_progress"]);

      expect(g.held.x).toBeGreaterThan(g.ready.x);
      expect(g.held.x).toBeLessThan(g.in_progress.x);
    });

    it("is drawn nearer the tier it shares the most paths with, and not after the last tier", () => {
      const g = joined(["held"], ["ready>held", "held>in_progress", "in_progress>held", "review>held"]);

      expect(Math.abs(g.held.x - g.in_progress.x)).toBeLessThan(Math.abs(g.held.x - g.ready.x));
      expect(g.held.x).toBeGreaterThanOrEqual(g.in_progress.x);
      expect(g.held.x).toBeLessThan(g.done.x);
    });
  });

  it("falls back to the Board's own columns with no tiers, every state placed", () => {
    const g = tiered(1920, 1080, undefined).galaxies;

    expect(Object.keys(g).sort()).toEqual([...SAVED_STATES].sort());
    for (const s of Object.values(g)) expect([Number.isFinite(s.x), Number.isFinite(s.y)]).toEqual([true, true]);
    expect(g.new.x).toBeLessThan(g.in_progress.x);
    expect(g.in_progress.x).toBeLessThan(g.done.x);
  });

  it("keeps the tiers in one row on a wide canvas and wraps them on a tall one", () => {
    const leftToRight = (g: ReturnType<typeof tiered>["galaxies"]) => ["new", "ready", "needs_attention", "in_progress", "review", "done"].every((id, i, ids) => !i || g[id].x > g[ids[i - 1]].x);

    expect(leftToRight(tiered(3440, 1440).galaxies)).toBe(true);
    expect(leftToRight(tiered(700, 1400).galaxies)).toBe(false);
  });

  it("tucks a run of single-state tiers above and below the row, each sun right of the last by at least the larger ring", () => {
    const g = tiered(1920, 1080).galaxies, run = ["needs_attention", "in_progress", "review"];

    expect(Math.sign(g.in_progress.y - g.needs_attention.y)).toBe(Math.sign(g.in_progress.y - g.review.y));
    expect(g.needs_attention.y).not.toBeCloseTo(g.in_progress.y);
    run.slice(1).forEach((id, i) => expect(g[id].x - g[run[i]].x).toBeGreaterThanOrEqual(Math.max(g[id].R, g[run[i]].R) - 1e-6));
    const all = Object.values(g);
    for (const a of all) for (const b of all) if (a !== b) expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(a.R + b.R - 1e-6);
  });

  describe("a state's side of the row", () => {
    /** Which side of the row's midline a state sits on: -1 high, 1 low, 0 on it. */
    const sideOf = (s: Scene, id: string) => {
      const d = s.galaxies[id].y - s.h / 2;
      return Math.abs(d) < 1 ? 0 : Math.sign(d);
    };
    /** The Board without these states and the paths that touch them, its tiers left as declared. */
    const without = (...ids: string[]) => (snap: Snapshot) => {
      const m = snap.flows[0].machine;
      m.states = m.states.filter((s) => !ids.includes(s.id));
      m.transitions = m.transitions.filter((t) => !ids.includes(t.source) && !ids.includes(t.target));
      m.mainLine = m.mainLine?.filter((id) => !ids.includes(id));
    };
    const sides = (s: Scene) => Object.fromEntries(DEFAULT_TIERS.flat().filter((id) => s.galaxies[id]).map((id) => [id, sideOf(s, id)]));
    const held = (s: Scene, full: Scene) => {
      const was = sides(full), now = sides(s);
      return Object.fromEntries(Object.keys(now).map((id) => [id, [now[id], was[id]]]));
    };
    const same = (pairs: Record<string, number[]>) => Object.fromEntries(Object.entries(pairs).map(([id, [a]]) => [id, [a, a]]));

    it("keeps every state on its side when the Needs Attention state is removed", () => {
      const full = tiered(1920, 1080), pairs = held(tiered(1920, 1080, DEFAULT_TIERS, without("needs_attention")), full);

      expect(Object.keys(pairs)).not.toContain("needs_attention");
      expect(pairs).toEqual(same(pairs));
    });

    it("keeps every state on its side when the Archived state is removed", () => {
      const full = tiered(1920, 1080), pairs = held(tiered(1920, 1080, DEFAULT_TIERS, without("archived")), full);

      expect(Object.keys(pairs)).toContain("done");
      expect(pairs).toEqual(same(pairs));
    });

    it("keeps every state on its side when a tier is added mid-row", () => {
      const added = [["new"], ["ready", "waiting"], ["blocked"], ["needs_attention"], ["in_progress"], ["review"], ["done", "archived"]];
      const full = tiered(1920, 1080), pairs = held(tiered(1920, 1080, added), full);

      expect(Object.keys(pairs)).toContain("in_progress");
      expect(pairs).toEqual(same(pairs));
    });
  });

  it("draws a state at one footprint and sun, busy or empty", () => {
    const busy = tiered(1920, 1080, DEFAULT_TIERS, (snap) => {
      snap.flows[0].agents = Array.from({ length: 64 }, (_, i) => ({ id: `ready-${i}`, title: "t", state: "ready", model: "", labels: [] }));
    }).galaxies;

    expect([busy.ready.R, busy.ready.r, busy.ready.moonR]).toEqual([busy.review.R, busy.review.r, busy.review.moonR]);
    expect(busy.ready.n).toBe(64);
  });

  it("draws the same footprint with nine machines under a state as with none, and no moon or pager for them", () => {
    const none = tiered(1920, 1080).galaxies, nine = tiered(1920, 1080, DEFAULT_TIERS, machinesOn("review", 9));

    expect(nine.moons).toEqual([]);
    // the machines crowd the Board, so its zoom drops and the suns grow to hold their names: the footprint past the sun is what stays
    expect(nine.galaxies.review.R - nine.galaxies.review.r).toBeCloseTo(none.review.R - none.review.r);
  });

  it("keeps today's sun-to-dot ratio and caps the zoom at 16 on a Board that would otherwise grow past it", () => {
    const small = tiered(3440, 1440, [["new"], ["done"]], (snap) => {
      snap.flows[0].machine.states = snap.flows[0].machine.states.filter((s) => ["new", "done"].includes(s.id));
      snap.flows[0].machine.transitions = [];
      snap.flows[0].machine.mainLine = ["new", "done"];
    });

    for (const s of Object.values(tiered(1920, 1080).galaxies)) expect(s.r).toBeGreaterThanOrEqual(SUN_R);
    expect(zoom(small, 3440)).toBeLessThanOrEqual(16 + 1e-6);
  });

  it("scales state names to 0.45 of the sun's screen radius, between 12 and 20 px", () => {
    // every state opens into machines, as the live Board's busiest states do: the fullest footprint the Board lays out
    const px = (W: number, H: number) => {
      const s = tiered(W, H, DEFAULT_TIERS, (snap) => {
        const ids = DEFAULT_TIERS.flat();
        snap.flows[0].machine.submachines = ids.map((state) => ({ state, machine: `m-${state}`, exits: {}, parent: "board", when: "" }));
        for (const state of ids) {
          snap.graphs.push(`m-${state}`);
          snap.flows.push({ name: `m-${state}`, agents: [], machine: machine(["a", "b"]) });
        }
      });
      // the nominal sun the type scale reads: the drawn suns grow past it to hold their names
      return { label: s.labelScale! * 13, sun: SUN_R * zoom(s, W) };
    };
    const small = px(1366, 768), mid = px(2560, 1440), big = px(3840, 2160);

    expect(small.label).toBeCloseTo(12);
    expect(mid.label).toBeCloseTo(0.45 * mid.sun);
    expect(mid.label).toBeGreaterThan(12);
    expect(mid.label).toBeLessThan(20);
    expect(big.label).toBeCloseTo(20);
  });

  it("wraps to another row only where that draws the sun more than 5% larger", () => {
    // the zoom each row count reaches, one row first
    expect(pickRows([1, 1.05, 1.04])).toBe(1);
    expect(pickRows([1, 1.0501])).toBe(2);
    expect(pickRows([1, 1.04, 1.06])).toBe(3);
    expect(pickRows([1, 1.04, 1.07, 1.09])).toBe(3);
    expect(pickRows([1])).toBe(1);
  });

  it.each([
    [1366, 768],
    [1920, 1080],
    [2560, 1440],
    [3440, 1440],
  ] as const)("draws the demo's eight states' names inside their suns, or hides a name its sun cannot grow to hold without costing the zoom, at 100, 125 and 150% text, at %i x %i", (W, H) => {
    const eight = (snap: Snapshot) => {
      const m = snap.flows[0].machine, gone = ["blocked", "completed"];
      m.states = m.states.filter((q) => !gone.includes(q.id));
      m.transitions = m.transitions.filter((t) => !gone.includes(t.source) && !gone.includes(t.target));
    };

    for (const scale of [100, 125, 150]) {
      expect(holds(tiered(W, H, DEFAULT_TIERS, eight, scale)), `${scale}%`).toBe(true);
    }
  });

  describe("with machines open under In Progress and Review, on a 1366 x 768 window whose side rails leave an 866 x 768 canvas (TASK-4243)", () => {
    const TIERS_14 = [["new"], ["triage"], ["ready", "waiting", "blocked"], ["needs_attention"], ["in_progress"], ["qa"], ["staging"], ["review"], ["approved"], ["done", "archived", "completed"]];
    const PATHS_14 = `new>triage triage>ready ready>in_progress in_progress>qa qa>staging staging>review review>approved approved>done done>completed
      ready>waiting waiting>ready ready>blocked blocked>ready in_progress>waiting waiting>in_progress in_progress>needs_attention needs_attention>ready
      needs_attention>in_progress qa>in_progress review>in_progress staging>qa review>done review>archived done>archived ready>archived new>ready
      new>in_progress triage>blocked blocked>needs_attention approved>archived qa>needs_attention waiting>archived completed>archived`.split(/\s+/).map((p) => p.split(">"));
    /** The demo's `?board=fourteen` states and paths. */
    const fourteen = (snap: Snapshot) => {
      const m = snap.flows[0].machine;
      m.states = TIERS_14.flat().map((id, i) => ({ id, name: id, initial: i === 0, final: ["archived", "completed"].includes(id) }));
      m.transitions = PATHS_14.map(([source, target]) => ({ source, target, event: `${source}_${target}` }));
      m.mainLine = ["new", "triage", "ready", "in_progress", "qa", "staging", "review", "approved", "done"];
      m.tiers = TIERS_14;
    };
    /** The demo's eight states, as the TASK-3839 table drew them. */
    const eight = (snap: Snapshot) => {
      const m = snap.flows[0].machine, gone = ["blocked", "completed"];
      m.states = m.states.filter((q) => !gone.includes(q.id));
      m.transitions = m.transitions.filter((t) => !gone.includes(t.source) && !gone.includes(t.target));
    };
    /** Two machines under each of In Progress and Review: the two states that draw a moon ring. */
    const rings = (snap: Snapshot) => {
      const m = snap.flows[0].machine;
      m.submachines = ["in_progress", "review"].flatMap((state) => [0, 1].map((i) => ({ state, machine: `${state}-${i}`, exits: {}, parent: "board", when: "" })));
      for (const { machine: flow } of m.submachines) {
        snap.graphs.push(flow);
        snap.flows.push({ name: flow, agents: [], machine: machine(["a", "b"]) });
      }
    };
    const suns = (shape: (snap: Snapshot) => void, tiers?: string[][]) =>
      [100, 125, 150].map((scale) => SUN_R * zoom(tiered(866, 768, tiers, (snap) => { shape(snap); rings(snap); }, scale), 866));

    it("keeps the fourteen states' suns at 12 px or more at 150% text, round the room their machines' branches take, when no zoom holds their names", () => {
      const [a, b, c] = suns(fourteen, TIERS_14);

      expect(c).toBeGreaterThanOrEqual(12);
      expect(a).toBeGreaterThanOrEqual(c);
      expect(b).toBeGreaterThanOrEqual(c);
    });

    it("draws the eight states' names inside their suns, round the room their machines' branches take, or hides a name its sun cannot grow to hold without costing the zoom", () => {
      for (const scale of [100, 125, 150]) {
        expect(holds(tiered(866, 768, DEFAULT_TIERS, (snap) => { eight(snap); rings(snap); }, scale)), `${scale}%`).toBe(true);
      }
    });
  });
});

describe("the Board's own columns, when no tiers are configured", () => {
  const MAIN = ["new", "ready", "in_progress", "review", "done"];
  const placed = (W = 1920, H = 1080) => build(savedBoardSky(W, H), { kind: "board" }).galaxies;

  it("runs the main line left to right in the order the snapshot declares", () => {
    const g = placed();

    MAIN.slice(1).forEach((id, i) => expect(g[id].x).toBeGreaterThan(g[MAIN[i]].x));
  });

  it("stacks each other open state in the column just before the latest main-line state it connects to", () => {
    const g = placed(), before = ["blocked", "waiting", "needs_attention"];

    before.forEach((id) => {
      expect(g[id].x).toBeCloseTo(g.blocked.x);
      expect(g[id].x).toBeGreaterThan(g.ready.x);
      expect(g[id].x).toBeLessThan(g.in_progress.x);
    });
    expect(new Set(before.map((id) => Math.round(g[id].y))).size).toBe(before.length);
  });

  it("stacks the final states in one column past the main line", () => {
    const g = placed();

    expect(g.completed.x).toBeCloseTo(g.archived.x);
    expect(g.completed.x).toBeGreaterThan(g.done.x);
    expect(g.completed.y).not.toBeCloseTo(g.archived.y);
  });

  it("places a Board it has never seen by the same rule, with no coordinates of its own", () => {
    const sky = savedBoardSky(1920, 1080, (snap) => {
      const m = snap.flows[0].machine;
      m.states.push({ id: "paused", name: "paused", initial: false, final: false });
      m.transitions.push({ source: "paused", target: "review", event: "paused_review" }, { source: "in_progress", target: "paused", event: "in_progress_paused" });
    }), g = build(sky, { kind: "board" }).galaxies;

    expect(g.paused.x).toBeGreaterThan(g.in_progress.x);
    expect(g.paused.x).toBeLessThan(g.review.x);
    expect(g.paused.y).not.toBe(g.new.y);
  });
});

describe("Board paths", () => {
  const crowdedCounts = { ready: 47, waiting: 35, in_progress: 7, done: 47, review: 1, needs_attention: 4, blocked: 12, archived: 9 };
  const crowd = (W: number, H: number, counts: Record<string, number>, patch: (snap: Snapshot) => void = () => {}) => savedBoardSky(W, H, (snap) => {
    snap.flows[0].machine.tiers = DEFAULT_TIERS;
    snap.flows[0].agents = Object.entries(counts).flatMap(([state, n]) => Array.from({ length: n }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
    patch(snap);
  });

  it.each([
    ["the base Board", 1920, 1080, {}],
    ["a busy Board", 1920, 1080, crowdedCounts],
    ["a stressed Board", 1670, 1080, Object.fromEntries(SAVED_STATES.map((s) => [s, 90]))],
  ])("pass nothing another state draws within 8 px on %s", (_, W, H, counts) => {
    const scene = build(crowd(W, H, counts), { kind: "board" }), close: string[] = [];

    for (const e of scene.bEdges)
      for (const g of Object.values(scene.galaxies))
        if (g.id !== e.source && g.id !== e.target && clearance(e as Curve, { ...g, R: g.edge }) < 8) close.push(`${e.source}>${e.target} by ${g.id}`);
    expect(close).toEqual([]);
  });

  it("pass no state's footprint within 17 px on a Board with room to bend round every one", () => {
    const scene = build(crowd(1670, 1080, Object.fromEntries(SAVED_STATES.map((s) => [s, 90]))), { kind: "board" }), close: string[] = [];

    for (const e of scene.bEdges)
      for (const g of Object.values(scene.galaxies))
        if (g.id !== e.source && g.id !== e.target && clearance(e as Curve, g) < 17) close.push(`${e.source}>${e.target} by ${g.id}`);
    expect(close).toEqual([]);
  });

  it("end just outside what each state draws: its sun when it holds no task, its outermost ring of tasks when it does, past its branches' root where machines map", () => {
    const sky = crowd(1920, 1080, { ready: 47 }, machinesOn("in_progress", 3)), scene = build(sky, { kind: "board" }), g = scene.galaxies;
    const ends = (id: string) => scene.bEdges.flatMap((e) => [...(e.source === id ? [e.p0!] : []), ...(e.target === id ? [e.p1!] : [])]).map((p) => Math.hypot(p.x - g[id].x, p.y - g[id].y));

    expect(ends("new").length * ends("ready").length * ends("in_progress").length).toBeGreaterThan(0);
    for (const d of ends("new")) expect(d).toBeCloseTo(g.new.r + 10);
    for (const d of ends("ready")) expect(d).toBeCloseTo(Math.max(...g.ready.rings!) + 10);
    for (const d of ends("in_progress")) expect(d).toBeCloseTo(g.in_progress.r + 18);
  });

  describe("on a Board of fourteen states and thirty-three paths", () => {
    const TIERS = [["new"], ["triage"], ["ready", "waiting", "blocked"], ["needs_attention"], ["in_progress"], ["qa"], ["staging"], ["review"], ["approved"], ["done", "archived", "completed"]];
    const PATHS = `new>triage triage>ready ready>in_progress in_progress>qa qa>staging staging>review review>approved approved>done done>completed
      ready>waiting waiting>ready ready>blocked blocked>ready in_progress>waiting waiting>in_progress in_progress>needs_attention needs_attention>ready
      needs_attention>in_progress qa>in_progress review>in_progress staging>qa review>done review>archived done>archived ready>archived new>ready
      new>in_progress triage>blocked blocked>needs_attention approved>archived qa>needs_attention waiting>archived completed>archived`.split(/\s+/).map((p) => p.split(">"));
    const board = (scale: number, W = 1920, H = 1080) => {
      const sky = savedBoardSky(W, H, (snap) => {
        const m = snap.flows[0].machine;
        m.states = TIERS.flat().map((id, i) => ({ id, name: id, initial: i === 0, final: ["archived", "completed"].includes(id) }));
        m.transitions = PATHS.map(([source, target]) => ({ source, target, event: `${source}_${target}` }));
        m.mainLine = ["new", "triage", "ready", "in_progress", "qa", "staging", "review", "approved", "done"];
        m.tiers = TIERS;
      });
      return build({ ...sky, scale }, { kind: "board" });
    };

    // a crowded canvas at a large text size cannot grow its suns without shrinking the Board past use, so the suns hold their radius and the
    // names that do not fit them are hidden: the Board never runs away to the minimum zoom, and no name spills past its sun
    it.each([[1070, 830, 150], [1318, 830, 150], [1070, 830, 125]])("keeps the suns bounded on a %i x %i canvas at %i% text, hiding the names they cannot hold", (W, H, scale) => {
      const s = board(scale, W, H), g = Object.values(s.galaxies);

      expect(Math.max(...g.map((x) => x.r))).toBeLessThan(SUN_R * 4);
      expect(holds(s)).toBe(true);
      expect(g.some((x) => x.text.length === 0)).toBe(true);
    });
  });

  it.each([100, 125, 150])("draw each state's name and count inside its sun at %i% text", (scale) => {
    const names = (snap: Snapshot) => { for (const st of snap.flows[0].machine.states) st.name = st.id.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" "); };
    const scene = build({ ...savedBoardSky(1920, 1080, names), scale }, { kind: "board" }), F = scene.labelScale! * scene.px!, out: string[] = [];

    // the name and count lines are stacked about the sun's centre in the type the canvas draws them in: a line's farthest corner is within the
    // black hole's shadow, which ends at SUN_FIT of the sun's radius
    for (const g of Object.values(scene.galaxies)) {
      for (const l of g.text) {
        const reach = Math.hypot(textW(l.text, l.size * F) / 2, Math.abs(l.y * F) + (l.size * F) / 2);
        if (reach > g.r * SUN_FIT) out.push(`${g.id} ${l.text}: ${reach.toFixed(1)} > ${(g.r * SUN_FIT).toFixed(1)}`);
      }
      // wrapping drops no word: the lines hold the name and count as they read on one line
      expect(g.text.map((l) => l.text).join(" ")).toBe(`${g.name} ${tally(g)}`.replaceAll(" \u00b7 ", " "));
    }
    expect(out).toEqual([]);
  });

  it("grows only the suns whose text needs the room", () => {
    const names = (snap: Snapshot) => { for (const st of snap.flows[0].machine.states) st.name = st.id.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" "); };
    const rs = Object.values(build({ ...savedBoardSky(1920, 1080, names), scale: 100 }, { kind: "board" }).galaxies).map((g) => g.r);

    expect(Math.min(...rs)).toBe(SUN_R);
    expect(Math.max(...rs)).toBeGreaterThan(SUN_R);
  });

  describe("sunTexts", () => {
    const rOf = (name: string, count: string) => sunTexts(name, count)[0].r;

    it("offers the fewest lines first, and a wrapped name needs a smaller sun than one long line", () => {
      const cands = sunTexts("Needs Attention Today", "3 \u00b7 2 today");

      expect(cands[0].lines.length).toBeLessThanOrEqual(cands[cands.length - 1].lines.length);
      expect(Math.min(...cands.map((c) => c.r))).toBeLessThan(cands[0].r);
    });

    it("breaks the count at its separator and the name at its spaces, dropping no word", () => {
      const cands = sunTexts("In Progress", "21 \u00b7 16 today");

      for (const c of cands) expect(c.lines.map((l) => l.text).join(" ").replaceAll(" \u00b7 ", " ")).toBe("In Progress 21 16 today");
      expect(cands.some((c) => c.lines.length === 4)).toBe(true);
    });

    it("grows the sun for a word that cannot wrap", () => {
      expect(rOf("Internationalisation", "1")).toBeGreaterThan(rOf("Done", "1"));
    });
  });

  it("gather into one stream along a final state's side when it is reached from several states", () => {
    // New, Ready and Done stacked in one tier, Archived alone in the next, reached from all three with nothing in their way
    const sky = savedBoardSky(1920, 1080, (snap) => {
      const m = snap.flows[0].machine;
      m.states = ["new", "ready", "done", "archived"].map((id, i) => ({ id, name: id, initial: i === 0, final: id === "archived" }));
      m.transitions = [["new", "ready"], ["ready", "done"], ["new", "archived"], ["ready", "archived"], ["done", "archived"]].map(([source, target]) => ({ source, target, event: `${source}_${target}` }));
      m.mainLine = ["new", "ready", "done"];
      m.tiers = [["new", "ready", "done"], ["archived"]];
    }), scene = build(sky, { kind: "board" }), into = scene.bEdges.filter((e) => e.target === "archived");

    expect(into).toHaveLength(3);
    // the sources above and below the middle one bend round it: the footprints keep no room for a name between the stacked states
    expect(into.find((e) => e.source === "ready")!.c!.y).toBeCloseTo(scene.galaxies.archived.y);
    for (const e of into) expect(e.p1!.x).toBeCloseTo(into[0].p1!.x, 0);
  });

  it("bow as one path when a pair is joined both ways, and run straight when it is one way", () => {
    const scene = build(savedBoardSky(1920, 1080), { kind: "board" }), mid = (e: Curve) => ({ x: (e.p0.x + e.p1.x) / 2, y: (e.p0.y + e.p1.y) / 2 });
    const edge = (s: string, t: string) => scene.bEdges.find((e) => e.source === s && e.target === t) as unknown as Curve;
    const off = (e: Curve) => Math.hypot(e.c.x - mid(e).x, e.c.y - mid(e).y);

    expect(off(edge("review", "in_progress"))).toBeGreaterThan(1);
    const there = edge("review", "in_progress"), back = edge("in_progress", "review");
    for (const [p, q] of [[back.p0, there.p1], [back.c, there.c], [back.p1, there.p0]]) expect([p.x, p.y]).toEqual([expect.closeTo(q.x, 6), expect.closeTo(q.y, 6)]);
    expect(off(edge("new", "ready"))).toBeLessThan(1);
  });

  // New, Ready and Review stacked in one tier, Done alone in the next
  const endBoard = (transitions: string[][]) => build(savedBoardSky(1920, 1080, (snap) => {
    const m = snap.flows[0].machine;
    m.states = ["new", "ready", "review", "done"].map((id, i) => ({ id, name: id, initial: i === 0, final: id === "done" }));
    m.transitions = transitions.map(([source, target]) => ({ source, target, event: `${source}_${target}` }));
    m.mainLine = ["new", "ready", "review"];
    m.tiers = [["new", "ready", "review"], ["done"]];
  }), { kind: "board" });
  const mirrored = (a: Curve, b: Curve) => {
    for (const [p, q] of [[b.p0, a.p1], [b.c, a.c], [b.p1, a.p0]]) expect([p.x, p.y]).toEqual([expect.closeTo(q.x, 6), expect.closeTo(q.y, 6)]);
  };

  it("draw a pair joined both ways as one control point in both directions when it bends round a state", () => {
    const scene = endBoard([["new", "ready"], ["ready", "review"], ["new", "review"], ["review", "new"]]);
    const there = scene.bEdges.find((e) => e.source === "new" && e.target === "review") as unknown as Curve, back = scene.bEdges.find((e) => e.source === "review" && e.target === "new") as unknown as Curve;

    expect(clearance(there, scene.galaxies.ready)).toBeGreaterThanOrEqual(17);
    mirrored(there, back);
  });

  it("keep a pair joined both ways into an end state off the stream that gathers its one-way paths", () => {
    const scene = endBoard([["new", "ready"], ["ready", "review"], ["review", "done"], ["done", "review"], ["ready", "done"], ["new", "done"]]);
    const edge = (s: string, t: string) => scene.bEdges.find((e) => e.source === s && e.target === t) as unknown as Curve, end = scene.galaxies.done.y;

    expect(edge("ready", "done").c.y).toBeCloseTo(end);
    expect(edge("new", "done").p1.x).toBeCloseTo(edge("ready", "done").p1.x, 0);
    expect(Math.abs(edge("review", "done").c.y - end)).toBeGreaterThan(10);
    mirrored(edge("review", "done"), edge("done", "review"));
  });

  it("merge every event between two states into one path per direction, carrying each event's writers", () => {
    const sky = savedBoardSky(1920, 1080, (snap) => {
      const m = snap.flows[0].machine;
      m.transitions.push({ source: "new", target: "waiting", event: "new_waiting_deps" });
      m.writers = { new_waiting: [{ actor: "a", trigger: "dagu" }], new_waiting_deps: [{ actor: "b", trigger: "dagu" }] };
    }), scene = build(sky, { kind: "board" });
    const pair = (s: string, t: string) => scene.bEdges.filter((e) => e.source === s && e.target === t);

    expect(pair("new", "waiting")).toHaveLength(1);
    expect(pair("new", "waiting")[0].events).toEqual(["new_waiting", "new_waiting_deps"]);
    expect(pair("new", "waiting")[0].event).toBe("new_waiting · new_waiting_deps");
    expect(pair("new", "waiting")[0].writers).toEqual([{ actor: "a", trigger: "dagu", event: "new_waiting" }, { actor: "b", trigger: "dagu", event: "new_waiting_deps" }]);
    expect([pair("ready", "waiting").length, pair("waiting", "ready").length]).toEqual([1, 1]);
  });
});

describe("the room between Board states", () => {
  const apart = (scene: ReturnType<typeof build>) => {
    const gs = Object.values(scene.galaxies), short: string[] = [];
    const px = scene.w / (0.94 * 1920);
    for (const a of gs) for (const b of gs) if (a.x < b.x && Math.abs(a.y - b.y) < a.R + b.R + 16 * px && b.x - b.R - (a.x + a.R) < 16 * px - 1e-6) short.push(`${a.id}/${b.id}`);
    return short;
  };
  const busy = (patch: (snap: Snapshot) => void = () => {}) => savedBoardSky(1920, 1080, (snap) => {
    snap.flows[0].agents = Object.entries({ ready: 90, waiting: 60, in_progress: 40, done: 90, review: 20 }).flatMap(([state, n]) => Array.from({ length: n }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
    patch(snap);
  });

  it("holds 16 px between a state's tasks and the next state beside it", () => {
    expect(apart(build(busy(), { kind: "board" }))).toEqual([]);
  });

  it("widens the sky to keep the canvas's shape when the states need more room", () => {
    const scene = build(busy(), { kind: "board" });

    expect(scene.w / scene.h).toBeCloseTo(1920 / 1080, 1);
  });
});

describe("the edge hit band", () => {
  const line = (y: number): Curve => ({ p0: { x: 0, y }, c: { x: 50, y }, p1: { x: 100, y } });
  const edges = [line(0), line(10)];
  const near = (x: number, y: number, band = 14) => nearestWithin(edges, (e) => curveDist(e, x, y), band);

  it("picks the nearest of two parallel edges within the band and none above it", () => {
    expect(near(50, 3)).toBe(edges[0]);
    expect(near(50, 8)).toBe(edges[1]);
    expect(near(50, -15)).toBeNull();
  });

  it("picks an edge from a point beside its end and none from one further along", () => {
    expect(near(110, 0)).toBe(edges[0]);
    expect(near(150, 0)).toBeNull();
  });

  it("measures to the line's end, not past it", () => {
    expect(curveDist(edges[0], 103, 4)).toBe(5);
  });
});

// PROJ-1 sits in In Progress; machine:events placed it on the in-progress machine at 800, on triaging-cr-reviews at 900 and back on in-progress at 980.
// The Board's In Progress state declares the exits the real board_links does: `review_recorded` fires REVIEW and `needs_attention` fires DEFER.
const inProgressSky = () => {
  const placed = (state: string, steps: [event: string, at: number][]) => ({ id: "PROJ-1", title: "t", state, model: "", task: "PROJ-1", trail: steps.map(([event, at]) => ({ state, event, at })) });
  const snap: Snapshot = {
    graphs: ["board", "in-progress", "triaging-cr-reviews"],
    flows: [
      { name: "board", agents: [{ id: "PROJ-1", title: "t", state: "in_progress", model: "", labels: [] }], machine: machine(["ready", "in_progress", "review", "needs_attention"], {
        transitions: [
          { source: "ready", target: "in_progress", event: "CLAIM" },
          { source: "in_progress", target: "review", event: "REVIEW" },
          { source: "in_progress", target: "needs_attention", event: "DEFER" },
        ],
        submachines: [{ state: "in_progress", machine: "in-progress", exits: { review_recorded: "REVIEW", needs_attention: "DEFER" }, parent: "board", when: "" }],
      }) },
      { name: "in-progress", agents: [placed("worktree_ready", [["WORKTREE", 800], ["BACK", 980]])], machine: machine(["worktree_ready", "pr_opened"]) },
      { name: "triaging-cr-reviews", agents: [placed("fetch", [["OPEN", 900]])], machine: machine(["fetch", "reply"]) },
    ],
    dags: [], domains: [], settled: {}, error: null, now: 1000,
  };
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W: 1920, H: 1080, T: 1000 };
};

describe("the In Progress state level's machine ledger top", () => {
  const at = (W: number, H: number, scale = 100) => build({ ...inProgressSky(), W, H, scale }, { kind: "state", id: "in_progress" });

  it("draws the in-progress machine across the top, its states, flow lines and tasks placed in the canvas", () => {
    const { top, mStates, mEdges, machineTasks } = at(1350, 900);
    expect([top?.machine, Object.keys(mStates)]).toEqual(["in-progress", ["worktree_ready", "pr_opened"]]);
    expect(machineTasks.map((t) => [t.id, t.machine])).toEqual([["PROJ-1", "in-progress"]]);
    expect(mEdges).toEqual([]);
    for (const s of Object.values(mStates)) expect([s.x > 0 && s.x < 1350, s.y > 0 && s.y < top!.hdrB]).toEqual([true, true]);
  });

  it("is half again its natural height, under 60% of the view", () => {
    const { top } = at(1350, 900);
    expect(top!.hdrB).toBeCloseTo(top!.natural * 1.5);
    expect(top!.hdrB).toBeLessThan(0.6 * 900);
  });

  it("stops at 60% of a short view", () => {
    const { top } = at(1350, Math.round(at(1350, 900).top!.natural / 0.48));
    expect(top!.hdrB).toBeLessThan(top!.natural * 1.5);
    expect(top!.hdrB).toBeGreaterThan(top!.natural);
  });

  it("is not on the Board", () => {
    expect(build(inProgressSky(), { kind: "board" }).top).toBeUndefined();
  });
});

describe("the In Progress state level", () => {
  const sky = inProgressSky(), scene = build(sky, { kind: "state", id: "in_progress" });

  it("puts a task on the machine it last moved in, the primary before and after", () => {
    expect([700, 850, 950, 990].map((t) => scene.hostAt!("PROJ-1", t))).toEqual(["in-progress", "in-progress", "triaging-cr-reviews", "in-progress"]);
  });

  it("joins the primary and a skill machine by one path each way, rim to rim", () => {
    const [pivot, skill] = scene.planets, dist = (a: Pt, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);
    const [out, back] = scene.hops;

    expect([pivot.name, skill.name]).toEqual(["in-progress", "triaging-cr-reviews"]);
    expect([out.from, out.to, out.back, back.from, back.to, back.back]).toEqual(["in-progress", "triaging-cr-reviews", false, "triaging-cr-reviews", "in-progress", true]);
    expect(dist(out.p0, pivot)).toBeCloseTo(pivot.rim!);
    expect(dist(out.p1, skill)).toBeCloseTo(skill.rim!);
    expect([back.p0, back.p1]).toEqual([out.p1, out.p0]);
  });

  it("sends each exit its SUBFLOW declares to the Board state its event moves to, and enters from the state that claims it", () => {
    const declared = Object.values(sky.S.board.machine.submachines![0].exits), target = (event: string) => scene.exits.find((x) => x.event === event)?.target;

    expect(declared.map(target)).toEqual(["review", "needs_attention"]);
    expect(scene.entries.map((x) => x.source)).toEqual(["ready"]);
  });
});

// In Progress has a branch (so it is the taller top); audit is entered from it, scan from audit, lint from scan, and `lonely` from nothing but In Progress.
const nestedSky = () => {
  const derived = (name: string, parent: string | null, chain: string[], m: Machine, agents: Snapshot["flows"][number]["agents"] = []): Snapshot["flows"][number] => ({
    name, agents, machine: m, parent, chain, depth: parent === null ? 0 : chain.length + 1, nested: [], ties: [], last: null, stuck: null,
  });
  const chain = (ids: string[]) => machine(ids, { transitions: ids.slice(1).map((t, i) => ({ source: ids[i], target: t, event: t.toUpperCase() })) });
  const branched = machine(["a", "b", "c", "d"], { transitions: [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]].map(([source, target]) => ({ source, target, event: target.toUpperCase() })) });
  const snap: Snapshot = {
    graphs: ["board", "in-progress", "audit", "scan", "lint", "lonely", "runs"],
    flows: [
      { name: "board", agents: [], machine: machine(["ready", "in_progress"], { submachines: [{ state: "in_progress", machine: "in-progress", exits: {}, parent: "board", when: "" }] }) },
      derived("in-progress", null, [], branched),
      derived("audit", "in-progress", [], chain(["x", "y"])),
      derived("scan", "audit", ["audit"], chain(["x", "y"])),
      derived("lint", "scan", ["audit", "scan"], chain(["x", "y"])),
      derived("lonely", "in-progress", [], chain(["x", "y"])),
    ],
    dags: [], domains: [], settled: {}, error: null, now: 1000,
  };
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W: 1350, H: 900, T: 1000, host: "in_progress" };
};

describe("a machine opened from a row", () => {
  const at = (flow: string) => build(nestedSky(), { kind: "machine", flow });

  it("takes the top, drawn at the height of the In Progress machine whatever its own flow", () => {
    const ip = build(nestedSky(), { kind: "state", id: "in_progress" }).top!, audit = at("audit").top!;

    expect([audit.machine, audit.nodes.map((n) => n.id)]).toEqual(["audit", ["x", "y"]]);
    expect(audit.hdrB).toBe(ip.hdrB);
    expect(at("lint").top!.hdrB).toBe(ip.hdrB);
  });

  it("makes the machines entered from it the rows, and a machine with none has no rows", () => {
    expect([at("audit"), at("scan"), at("lint"), at("lonely")].map((sc) => sc.top!.rows.map((r) => r.name))).toEqual([["scan"], ["lint"], [], []]);
  });

  it("states what an empty lane means, naming the machine", () => {
    expect(emptyNote("lint")).toBe("nothing is entered from lint · Esc steps back out");
  });

  it("puts the machine's own states, flow lines and tasks on the level for the hover and panels", () => {
    const sc = at("audit");
    expect(Object.keys(sc.mStates)).toEqual(["x", "y"]);
    expect(sc.mEdges.map((e) => [e.source, e.target])).toEqual([["x", "y"]]);
  });
});

describe("a state's self-transitions", () => {
  const stays = () => {
    const S = sky();
    S.S.flows["in-progress"].machine.transitions.push({ source: "pr_opened", target: "pr_opened", event: "PR_UPDATED" }, { source: "pr_opened", target: "pr_opened", event: "REVIEWED" });
    return S;
  };

  it("lists each on the state instead of drawing a loop, on a machine level and a state level", () => {
    const inMachine = build(stays(), { kind: "machine", flow: "in-progress" }), inState = build(stays(), { kind: "state", id: "in_progress" });
    const primary = inState.planets.find((p) => p.primary)!;

    expect(inMachine.mStates.pr_opened.loops).toEqual(["PR_UPDATED", "REVIEWED"]);
    expect(primary.states.pr_opened.loops).toEqual(["PR_UPDATED", "REVIEWED"]);
    expect(inMachine.mStates.worktree_ready.loops).toEqual([]);
  });
});

// In Progress opens into its primary machine and `skills` more. The primary's pr_opened and every third skill's `reading` hold a sub-state that opens
// a child machine. PROJ-1 sits in pr_opened, PROJ-2 works skill-00, PROJ-3 is in the primary outside any sub-state, PROJ-4 is in Ready.
const moonSky = (skills = 2, W = 1920, H = 1080, ties: { writes?: Record<string, string[]>; cues?: Cue[]; launches?: Record<string, string>; busy?: number } = {}) => {
  const { writes = {}, cues = [], launches = {}, busy = 0 } = ties, writers: Record<string, { actor: string; trigger: string }[]> = {};
  for (const [name, events] of Object.entries(writes)) for (const e of events) (writers[e] ||= []).push({ actor: name, trigger: "dagu" });
  const tied = [...new Set([...Object.keys(writes), ...cues.map((c) => c.dag), ...Object.keys(launches)])];
  const names = Array.from({ length: skills }, (_, i) => `skill-${String(i).padStart(2, "0")}`);
  const session = (task: string, state: string, active: number) => ({ id: `${task}-${state}`, title: "t", state, model: "", task, active });
  const link = (state: string, parent: string) => ({ state, machine: "running-skill-evals", exits: {}, parent, when: "it reads" });
  // `busy` more tasks work the first twelve skills, dealt round in turn
  const extra = Array.from({ length: busy }, (_, i) => `TASK-${10 + i}`);
  const snap: Snapshot = {
    graphs: ["board", "in-progress", "triaging-cr-reviews", "running-skill-evals", ...names, "runs"],
    flows: [
      { name: "board", agents: ["PROJ-1", "PROJ-2", "PROJ-3", ...extra].map((id) => ({ id, title: "t", state: "in_progress", model: "", labels: [] })).concat([{ id: "PROJ-4", title: "t", state: "review", model: "", labels: [] }]),
        machine: machine(["ready", "in_progress", "review"], {
          transitions: [{ source: "ready", target: "in_progress", event: "CLAIM" }, { source: "in_progress", target: "review", event: "REVIEW" }],
          submachines: [{ state: "in_progress", machine: "in-progress", exits: {}, parent: "board", when: "" }],
          writers, launches: Object.fromEntries(Object.entries(launches).map(([d, flow]) => [d, { skill: "delivering", machine: flow }])),
        }) },
      { name: "in-progress", agents: [session("PROJ-1", "pr_opened", 900), session("PROJ-3", "worktree_ready", 950)], machine: machine(["worktree_ready", "pr_opened"], {
        submachines: [{ state: "pr_opened", machine: "triaging-cr-reviews", exits: {}, parent: "in-progress", when: "a PR is open" }],
      }) },
      { name: "triaging-cr-reviews", agents: [], machine: machine(["fetch", "reply"]) },
      { name: "running-skill-evals", agents: [], machine: machine(["run", "score"]) },
      ...names.map((name, i) => ({ name, agents: [...(i ? [] : [session("PROJ-2", "writing", 980)]), ...extra.filter((_, j) => j % 12 === i).map((t) => session(t, "writing", 980))], machine: machine(["reading", "writing"], { submachines: i % 3 === 0 ? [link("reading", name)] : [] }) })),
    ],
    dags: tied.map((n) => dag(n, [["run", []]])), domains: [{ name: "Board", dags: tied.map((name) => ({ name, runSafe: false })) }], cues, settled: {}, error: null, now: 1000,
  };
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W, H, T: 1000 };
};

describe("a Board state's machines", () => {
  const board = (skills: number) => build(moonSky(skills), { kind: "board" });

  it("holds the state at one size, whether it opens into two machines or twenty", () => {
    const base = board(2).galaxies.in_progress, stress = board(20).galaxies.in_progress;

    // twenty machines may crowd the zoom down and the sun up to hold its name: what stands past the sun stays
    expect(stress.R - stress.r).toBeCloseTo(base.R - base.r);
    expect(stress.edge - stress.r).toBeCloseTo(base.edge - base.r);
  });

  it("counts every task of a state on the state, wherever it orbits", () => {
    expect(board(4).galaxies.in_progress.n).toBe(3);
  });
});

describe("the state level's lifecycle moons", () => {
  const level = (skills: number) => build(moonSky(skills), { kind: "state", id: "in_progress" });
  const moonsOf = (scene: Scene) => scene.planets.filter((p) => p.moon && !p.pager);
  /** The quarter of the ring a moon sits in, from the primary: right or left, upper or lower. */
  const quarter = (scene: Scene, m: Pt) => [Math.sign(m.x - scene.pivot!.x), Math.sign(m.y - scene.pivot!.y)];

  it("sets the skill machines round the primary, alternating right and left, then upper and lower", () => {
    const scene = level(6);

    expect(scene.planets[0]).toBe(scene.pivot);
    expect(moonsOf(scene).map((m) => [m.name, ...quarter(scene, m)])).toEqual([
      ["skill-00", 1, -1], ["skill-01", -1, -1], ["skill-02", 1, 1], ["skill-03", -1, 1], ["skill-04", 1, -1], ["skill-05", -1, -1],
    ]);
  });

  it("stacks each quarter's rows from the band beside the primary out to four-fifths of one ring, however many machines there are", () => {
    for (const n of [2, 20]) {
      const scene = level(n), pivot = scene.pivot!, moons = moonsOf(scene), ring = Math.hypot(moons[0].x - pivot.x, moons[0].y - pivot.y);

      for (const m of moons) {
        expect(Math.hypot(m.x - pivot.x, m.y - pivot.y)).toBeCloseTo(ring);
        expect(Math.abs(m.y - pivot.y)).toBeGreaterThan(pivot.rim! + 70);
        expect(Math.abs(m.y - pivot.y)).toBeLessThanOrEqual(0.8 * ring + 1);
      }
      for (const q of [[1, -1], [-1, -1], [1, 1], [-1, 1]]) {
        const rows = moons.filter((m) => quarter(scene, m).join() === q.join()).sort((a, b) => Math.abs(a.y - pivot.y) - Math.abs(b.y - pivot.y));
        rows.forEach((m, i) => { if (i) expect(Math.abs(m.y - rows[i - 1].y)).toBeGreaterThanOrEqual(m.rim! + rows[i - 1].rim!); });
      }
    }
  });

  it("grows the ring until every quarter's rows fit", () => {
    const ring = (n: number) => { const s = level(n), m = moonsOf(s)[0]; return Math.hypot(m.x - s.pivot!.x, m.y - s.pivot!.y); };

    expect(ring(20)).toBeGreaterThan(ring(2));
  });

  // the view fits the level's frame on every snapshot, so a frame that changed with the page would move the primary on screen
  it("keeps the primary, related DAGs and the level's frame fixed while its stressed machine page changes", () => {
    const fixture = moonSky(20, 1920, 1080, { writes: { claimer: ["CLAIM"], reviewer: ["REVIEW"] } });
    const page = (at: number) => build({ ...fixture, pages: { in_progress: at } }, { kind: "state", id: "in_progress" });
    const first = page(0), second = page(1), at = (scene: Scene) => ({
      box: scene.box,
      pivot: [scene.pivot!.x, scene.pivot!.y],
      dags: Object.fromEntries(Object.entries(scene.stars).map(([id, s]) => [id, [s.x, s.y]])),
    });

    expect(second.planets.filter((p) => p.moon).map((p) => p.name)).not.toEqual(first.planets.filter((p) => p.moon).map((p) => p.name));
    expect(first.planets.filter((p) => p.pager).map((p) => p.name)).toEqual(["‹ 2/2", "2/2 ›"]);
    expect(second.planets.filter((p) => p.pager).map((p) => p.name)).toEqual(["‹ 1/2", "1/2 ›"]);
    expect(at(second)).toEqual(at(first));
  });

  it("frames the level to what it draws, the pager nodes included, with no margin of its own", () => {
    for (const n of [2, 20]) {
      const scene = level(n), pivot = scene.pivot!, ring = Math.hypot(moonsOf(scene)[0].x - pivot.x, moonsOf(scene)[0].y - pivot.y);

      expect(scene.box![2] - pivot.x).toBeLessThan(ring + 260);
      for (const p of scene.planets.filter((p) => p.pager)) expect(scene.box![3]).toBeGreaterThanOrEqual(p.y + p.rim!);
    }
  });

  it("pages with two machine nodes on the bottom of the ring, back on the left and forward on the right", () => {
    const scene = level(20), pivot = scene.pivot!, ring = Math.hypot(moonsOf(scene)[0].x - pivot.x, moonsOf(scene)[0].y - pivot.y), [back, forward] = scene.planets.filter((p) => p.pager);

    expect([back.pager!.d, forward.pager!.d, back.R, forward.R]).toEqual([-1, 1, 9, 9]);
    for (const p of [back, forward]) {
      expect(Math.hypot(p.x - pivot.x, p.y - pivot.y)).toBeCloseTo(ring);
      expect(p.y).toBeGreaterThan(Math.max(...moonsOf(scene).map((o) => o.y)));
    }
    expect([back.x - pivot.x, back.y]).toEqual([pivot.x - forward.x, forward.y]);
    expect(forward.x - back.x).toBeGreaterThanOrEqual(back.rim! + forward.rim!);
  });
});

describe("the state level's sub-state chains", () => {
  const scene = build(moonSky(4), { kind: "state", id: "in_progress" }), pivot = scene.pivot!;
  const moon = (name: string) => scene.planets.find((p) => p.name === name)!;
  const chainOf = (name: string) => scene.planets.filter((p) => p.subState && p.machine === name);

  it("chains a skill machine's sub-states outward from its moon along its row, and names the chain past it", () => {
    const m = moon("skill-00"), [b] = chainOf("skill-00"), out = Math.sign(m.x - pivot.x);

    expect([b.state, b.flow, b.y, (b.x - m.x) * out > 0]).toEqual(["reading", "running-skill-evals", m.y, true]);
    expect(Math.abs(b.x - m.x)).toBeGreaterThanOrEqual(m.rim! + b.rim!);
    expect(m.chain).toEqual([b]);
    expect(m.label).toBe("skill-00 › reading");
  });

  it("gives a machine with no sub-state no chain and no label, and draws the primary's own sub-state as no chain", () => {
    expect([chainOf("skill-01"), moon("skill-01").label, chainOf("in-progress")]).toEqual([[], undefined, []]);
  });

  it("boxes the level past the end of the longest chain label, so no label reaches the Board paths drawn at the screen edge", () => {
    const m = moon("skill-00"), [b] = chainOf("skill-00"), [x0, , x1] = scene.box!, out = Math.sign(m.x - pivot.x);
    const labelEnd = b.x + out * (b.rim! + (textW(m.label!, 11.5) * scene.moonLH!) / 17);

    expect(out > 0 ? x1 : -x0).toBeGreaterThanOrEqual(out * labelEnd);
  });

  it("keeps a sub-state off the hops between machines", () => {
    expect(scene.hops.flatMap((h) => [h.from, h.to]).filter((n) => n.includes(">"))).toEqual([]);
  });
});

describe("the state level's tasks", () => {
  // PROJ-1 holds the primary's pr_opened (no body drawn for it), PROJ-2 reads skill-00 (a sub-state) and PROJ-3 writes skill-01 (no sub-state).
  const level = () => {
    const sky = moonSky(4), move = (task: string, flow: string, to: string, at: number) => ({ machine: flow, task, at, event: "MOVE", to, from: null });
    sky.moves.events.push(move("PROJ-1", "in-progress", "pr_opened", 900), move("PROJ-2", "skill-00", "reading", 920), move("PROJ-3", "skill-01", "writing", 940));
    return build(sky, { kind: "state", id: "in_progress" });
  };
  const hostsOf = (scene: Scene, id: string) => scene.tasks.filter((t) => t.id === id).map((t) => t.host.name);

  it("orbit the deepest body drawn: a sub-state, else the machine's moon, else the primary, with a place on each body visited in the hour", () => {
    const scene = level();

    expect(["PROJ-1", "PROJ-2", "PROJ-3"].map((id) => scene.hostAt!(id, 1000))).toEqual(["in-progress", "skill-00>reading", "skill-01"]);
    expect([hostsOf(scene, "PROJ-1"), hostsOf(scene, "PROJ-2"), hostsOf(scene, "PROJ-3")]).toEqual([["in-progress"], ["in-progress", "skill-00>reading"], ["in-progress", "skill-01"]]);
  });

  it("widen a row to the orbits of the body they sit on", () => {
    const scene = level(), body = scene.planets.find((p) => p.name === "skill-00>reading")!;

    expect(body.rim).toBeGreaterThan(13);
    expect(scene.planets.find((p) => p.name === "skill-00")!.chain![0]).toBe(body);
  });
});

describe("a fold's level", () => {
  const fold = (path: [string, string] | null, event?: string): Level => ({ kind: "fold", event, dags: ["alpha", "beta", "delta"], crit: [], path });
  const cues: Cue[] = [
    { dag: "beta", event: "CLAIM", state: "in_progress", on: "each merge", resolves: "next" },
    { dag: "delta", event: "CLAIM", state: "in_progress", on: "each claim", resolves: "forced" },
    { dag: "beta", event: "MERGED", state: "done", on: "push to main", resolves: "next" },
  ];
  const sky = () => boardSky({ writes: { alpha: ["CLAIM"] }, cues, free: { Other: ["loose"] } });
  const ledger = (level = fold(["ready", "in_progress"], "CLAIM"), scale?: number) => build({ ...sky(), scale }, level);

  it("lays the event's DAGs as templates in one row, the DAG that writes it first and each cue after it", () => {
    const { stars } = ledger();

    expect(Object.keys(stars)).toEqual(["alpha", "beta", "delta"]);
    expect(stars.alpha.x).toBeLessThan(stars.beta.x);
    expect(stars.beta.x).toBeLessThan(stars.delta.x);
    expect(new Set(Object.values(stars).map((s) => s.y)).size).toBe(1);
  });

  it("runs the path between its two states with the event marked above the DAG that writes it", () => {
    const f = ledger().fold!, l = f.ledger!, alpha = ledger().stars.alpha;

    expect([f.a!.id, f.b!.id, f.a!.y === f.b!.y]).toEqual(["ready", "in_progress", true]);
    expect([l.event, l.mark.x, l.mark.y]).toEqual(["CLAIM", alpha.x, f.a!.y]);
    expect(l.mark.x).toBeGreaterThan(f.p0!.x);
    expect(l.mark.x).toBeLessThan(f.p1!.x);
  });

  it("marks the event mid-path when no DAG writes it, only cues", () => {
    const f = ledger(fold(["review", "done"], "MERGED")).fold!;

    expect(f.ledger!.mark.x).toBeCloseTo((f.p0!.x + f.p1!.x) / 2);
  });

  it("hangs the junction under the path's first state, level with the templates, and a cue bus below them", () => {
    const scene = ledger(), f = scene.fold!, l = f.ledger!, row = scene.stars.alpha;

    expect([l.J.x, l.J.y]).toEqual([f.a!.x, row.y]);
    expect(l.J.y).toBeGreaterThan(f.a!.y + f.a!.r);
    expect(l.bus).toBeGreaterThan(row.y + row.glyph.h / 2);
  });

  it("gives each template a caption cell that names its role and contract, side by side without overlap", () => {
    const scene = ledger(), cols = scene.fold!.ledger!.cols;

    expect(cols.map((c) => [c.dag, c.role, c.on, c.resolves])).toEqual([["alpha", "writer", "dagu", null], ["beta", "cue", "each merge", "next"], ["delta", "cue", "each claim", "forced"]]);
    cols.forEach((c, i) => {
      expect([c.x0 < scene.stars[c.dag].x, scene.stars[c.dag].x < c.x1]).toEqual([true, true]);
      if (i) expect(c.x0).toBeGreaterThanOrEqual(cols[i - 1].x1);
    });
  });

  it("opens from every Board transition a DAG writes or is cued by, MERGED or not", () => {
    const sk = sky(), src = { flows: [sk.S.board], cues: sk.S.cues };

    for (const [event, rows] of [["CLAIM", "task"], ["MERGED", "merge"]] as const) expect(build(sk, ledgerLevel(src, event)!).fold!.ledger).toMatchObject({ event, rows });
  });

  describe("a merge Ledger's rows", () => {
    const row = (key: string, at: number, over: Partial<LedgerRow> = {}): LedgerRow => ({ key, at, tasks: [`TASK-${at}`], sha: key.repeat(7), runs: {}, fails: {}, pinned: false, ...over });
    const rows = [row("c", 300), row("b", 200, { appliedBy: "c" }), row("a", 100, { appliedBy: "gone" }), row("z", 50, { appliedBy: null })];
    const merged = (list: LedgerRow[] = rows, scale?: number, mergePins?: LedgerRow[]) => {
      const sk = boardSky({ writes: { alpha: ["MERGED"] }, cues: cues.filter((c) => c.event === "MERGED"), ledgers: { MERGED: list }, mergePins });
      return build({ ...sk, scale }, fold(["review", "done"], "MERGED"));
    };

    it("hang a viewport under the cue bus, whole rows tall, and one cell template in each template's column", () => {
      const scene = merged(), l = scene.fold!.ledger!, g = l.grid!;

      expect(g.top).toBeGreaterThan(l.bus);
      expect([g.view / g.rh, g.view % g.rh]).toEqual([rows.length + 1, 0]);
      expect(g.cells.map((c) => c.dag)).toEqual(l.cols.map((c) => c.dag));
      g.cells.forEach((c, i) => expect([c.gx > l.cols[i].x0, c.tx < l.cols[i].x1, c.room > 0]).toEqual([true, true, true]));
    });

    it("keep the left gutter wide enough for a row's time, task and title before the spine", () => {
      const g = merged().fold!.ledger!.grid!, bare = merged([]).fold!.ledger!;

      expect(g.label.w).toBeGreaterThan(150);
      expect(g.label.x + g.label.w).toBeLessThan(merged().fold!.ledger!.J.x);
      expect(bare.grid).toBeUndefined();
    });

    it("put the cross lane just past the spine", () => {
      expect(merged().fold!.ledger!.grid!.lane).toBeGreaterThan(merged().fold!.ledger!.J.x);
    });

    it("size the viewport to the rows that fit the level, however many are loaded, and grow the fit box to hold it", () => {
      const many = Array.from({ length: 80 }, (_, i) => row(`m${i}`, 1000 - i)), scene = merged(many), g = scene.fold!.ledger!.grid!;

      expect(g.view / g.rh).toBeLessThan(80);
      expect(g.view / g.rh).toBeGreaterThanOrEqual(1);
      expect(g.top + g.view + g.rh / 2).toBeLessThanOrEqual(scene.box![3]);
      expect(scene.box![3]).toBeLessThanOrEqual(scene.h);
    });

    it("reserve the 24-hour strip under the viewport, spine to the right margin, inside the fit box", () => {
      const scene = merged(), g = scene.fold!.ledger!.grid!, { u, F } = px(scene);

      expect([g.strip.x0, g.strip.x1]).toEqual([scene.fold!.ledger!.J.x, scene.w - 70 * u]);
      expect(g.strip.y).toBeCloseTo(g.top + g.view + 44 * F);
      expect(g.strip.y + g.strip.h / 2).toBeLessThanOrEqual(scene.box![3]);
    });

    describe("with merges pinned by an open failure", () => {
      const open = { runId: "r", step: "apply", startedAt: "", finishedAt: "", resolves: "forced" as const, resolved: null };
      const pin = (key: string, at: number) => row(key, at, { pinned: true, fails: { alpha: open } });

      it("add the band's pins and a gap to the viewport, which still holds every row and the footer", () => {
        const none = merged().fold!.ledger!.grid!, g = merged([row("c", 300), pin("b", 200), pin("a", 100), row("z", 50)]).fold!.ledger!.grid!;

        expect([none.pins, g.pins]).toEqual([0, 2]);
        expect(g.view).toBeCloseTo(none.view + g.gap);
        expect(g.gap).toBeGreaterThan(0);
      });

      it("count a pin the head left out, and show no more than half the viewport's rows", () => {
        const out = merged(rows, undefined, [pin("old", 10)]).fold!.ledger!.grid!;
        const many = Array.from({ length: 80 }, (_, i) => pin(`m${i}`, 1000 - i)), full = merged(many).fold!.ledger!.grid!;

        expect(out.pins).toBe(1);
        expect(out.view).toBeCloseTo(merged().fold!.ledger!.grid!.view + out.rh + out.gap);
        expect(full.pins).toBe(full.cap);
        expect(full.cap).toBeLessThanOrEqual(Math.max(1, Math.floor(full.view / full.rh / 2)));
      });
    });

    // the approved mockup (starpulse#95, view C) lays the Ledger out in screen pixels: u world units a pixel, F one at the reader's text size
    const px = (scene: Scene, scale = 100) => ({ u: scene.w / 1920, F: (scene.w / 1920) * (scale / 100) });

    it("lay the path, the gutter and the columns out in the mockup's proportions", () => {
      for (const scale of [100, 150]) {
        const scene = merged(rows, scale), f = scene.fold!, l = f.ledger!, g = l.grid!, { u, F } = px(scene, scale), lt = Math.min(340 * F, 0.26 * scene.w);

        expect([f.a!.x, l.J.x, f.a!.y, f.a!.r]).toEqual([64 * u + lt, 64 * u + lt, 62 * F, 22 * u]);
        expect(f.b!.x).toBeCloseTo(scene.w - 40 * u - 60 * F);
        expect(l.cols[0].x0).toBeCloseTo(l.J.x + 46 * F);
        expect(l.cols.at(-1)!.x1).toBeCloseTo(scene.w - 70 * u);
        expect([g.label.x, g.label.w]).toEqual([64 * u, lt - 10 * u]);
        // a one-step template is a single node 5 px in radius, so the tallest template here is 10 px
        expect(l.J.y).toBeCloseTo(f.a!.y + 64 * F + 5 * u);
      }
    });

    it("hang each row's mini graph under its template, rows the mockup's 60 px tall at least", () => {
      for (const scale of [100, 200]) {
        const scene = merged(rows, scale), l = scene.fold!.ledger!, g = l.grid!, { u, F } = px(scene, scale);

        expect(g.cells.map((c) => c.gx)).toEqual(l.cols.map((c) => scene.stars[c.dag].x));
        expect(g.rh).toBeCloseTo(Math.max(60 * u, 34 * F));
      }
    });

    it("scale a wide fan's template and mini graph to the mockup's apply-on-merge, and grow the rows to hold the mini", () => {
      const sk = boardSky({ writes: { alpha: ["MERGED"] }, cues: cues.filter((c) => c.event === "MERGED"), ledgers: { MERGED: rows } });
      sk.S.dagBy.beta.steps = [{ name: "r", depends: [], status: "succeeded", kind: null, precondition: null, lock: null, last: [] as [] }, ...Array.from({ length: 9 }, (_, i) => ({ name: `s${i}`, depends: ["r"], status: "succeeded" as const, kind: null, precondition: null, lock: null, last: [] as [] })), { name: "z", depends: Array.from({ length: 9 }, (_, i) => `s${i}`), status: "succeeded", kind: null, precondition: null, lock: null, last: [] as [] }];
      const scene = build(sk, fold(["review", "done"], "MERGED")), g = scene.fold!.ledger!.grid!, { u } = px(scene), fan = glyph(sk.S.dagBy.beta), cell = g.cells[1];

      expect([fan.w, fan.h]).toEqual([56, 144]);
      expect(scene.stars.beta.glyph.h).toBeCloseTo(104 * u);
      expect(scene.stars.beta.glyph.h * cell.ms).toBeCloseTo(43 * u);
      expect(g.rh).toBeCloseTo(43 * u + 2 * g.nr + 12 * u);
    });

    it("is loading, with no grid, until the stream's first page arrives, and not once an empty page has", () => {
      const sky = (ledgers: Record<string, LedgerRow[]>) => boardSky({ writes: { alpha: ["MERGED"] }, cues: cues.filter((c) => c.event === "MERGED"), ledgers });
      const led = (ledgers: Record<string, LedgerRow[]>) => build(sky(ledgers), fold(["review", "done"], "MERGED")).fold!.ledger!;

      expect([led({}).loading, led({}).grid]).toEqual([true, undefined]);
      expect([led({ MERGED: [] }).loading, led({ MERGED: rows }).loading]).toEqual([false, false]);
    });

    it("never loads for a task event's Ledger, which holds no merge rows", () => {
      const sk = boardSky({ writes: { alpha: ["CLAIM"] }, cues });

      expect(build(sk, fold(["ready", "in_progress"], "CLAIM")).fold!.ledger!.loading).toBe(false);
    });

    it("draws a task event's Ledger with no rows even when merges are loaded", () => {
      const sk = boardSky({ writes: { alpha: ["CLAIM"] }, cues, ledgers: { MERGED: rows } });

      expect(build(sk, fold(["ready", "in_progress"], "CLAIM")).fold!.ledger!.grid).toBeUndefined();
    });
  });

  it("gives a merge's Ledger rows of merges and any other event's rows of tasks", () => {
    expect([ledger().fold!.ledger!.rows, ledger(fold(["review", "done"], "MERGED")).fold!.ledger!.rows]).toEqual(["task", "merge"]);
  });

  it("frames the path ends and every template", () => {
    const scene = ledger(), [x0, y0, x1, y1] = scene.box!, f = scene.fold!;

    for (const s of Object.values(scene.stars)) expect([s.x > x0, s.x < x1, s.y > y0, s.y < y1]).toEqual([true, true, true, true]);
    expect([f.a!.x - f.a!.r > x0, f.b!.x + f.b!.r < x1, f.ledger!.bus < y1]).toEqual([true, true, true]);
  });

  it("leaves the gutter its junction's label needs, wider as the text scale grows, and still keeps the cells apart", () => {
    const at = (scale: number) => ledger(undefined, scale).fold!;

    expect(at(150).a!.x).toBeGreaterThan(at(100).a!.x);
    at(150).ledger!.cols.forEach((c, i, cols) => i && expect(c.x0).toBeGreaterThanOrEqual(cols[i - 1].x1));
  });

  it("lays DAGs that sit beside one state in a row, with no path or Ledger drawn", () => {
    const scene = ledger(fold(null)), f = scene.fold!;

    expect([f.a, f.b, f.ledger]).toEqual([undefined, undefined, undefined]);
    expect(Object.keys(scene.stars)).toEqual(["alpha", "beta", "delta"]);
  });
});

describe("a Board drawn again", () => {
  const geom = (s: Scene) => ({
    edges: s.bEdges.map((e) => [e.event, e.p0, e.c, e.p1]),
    stars: Object.values(s.stars).map((q) => [q.name, q.x, q.y, q.tether?.x, q.tether?.y]),
  });
  const routedSky = () => savedBoardSky(1920, 1080), dagSky = () => boardSky({ writes: { alpha: ["CLAIM"], beta: ["CLAIM"], solo: ["MERGED"], chain: ["REVIEW"] } });

  it.each([["routed paths", routedSky, dagSky], ["settled DAG bodies", dagSky, routedSky]])(
    "lays out its %s exactly as it would afresh, whatever was drawn between and however the last scene was changed",
    (_, sky, other) => {
      const fresh = geom(build(sky(), { kind: "board" }));
      build(other(), { kind: "board" });
      const again = build(sky(), { kind: "board" });
      expect(geom(again)).toEqual(fresh);
      for (const e of again.bEdges) if (e.c) e.c.x += 500;
      for (const q of Object.values(again.stars)) q.x += 500;
      expect(geom(build(sky(), { kind: "board" }))).toEqual(fresh);
    },
  );

  it("lays a Board out afresh when its tiers change, and when only a state's tasks do moves nothing but the ends of its paths", () => {
    const placed = (s: Scene) => ({ ...geom(s), edges: s.bEdges.map((e) => [e.event, e.c]), states: Object.values(s.galaxies).map((g) => [g.id, g.x, g.y, g.R]) });
    const before = placed(build(dagSky(), { kind: "board" })), busy = dagSky(), moved = dagSky();
    busy.S.flows.board.agents = Array.from({ length: 40 }, (_, i) => ({ id: `T-${i}`, title: "t", state: "review", model: "", labels: [] })) as never;
    moved.S.flows.board.machine.tiers = [["review"], ["ready"]];
    expect(placed(build(busy, { kind: "board" }))).toEqual(before);
    expect(placed(build(moved, { kind: "board" }))).not.toEqual(before);
  });
});

describe("a Board state's self-transitions", () => {
  it("lists each on the state instead of drawing a loop over it, as a machine level does", () => {
    const scene = build(boardSky(), { kind: "board" });

    expect(scene.bEdges.filter((e) => e.source === e.target)).toEqual([]);
    expect(scene.galaxies.in_progress.loops).toEqual(["STAY"]);
    expect(scene.galaxies.ready.loops).toEqual([]);
  });
});

describe("a sun's size", () => {
  const withTasks = (counts: Record<string, number>) => {
    const s = boardSky();
    s.S.board.agents = Object.entries(counts).flatMap(([state, n]) => Array.from({ length: n }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
    return s;
  };

  it("grows the primary on a state level with machines so every task circles it in one ring", () => {
    const pivot = build(withTasks({ in_progress: 200 }), { kind: "state", id: "in_progress" }).pivot!;

    expect([pivot.R > 104, pivot.rings?.length]).toEqual([true, 1]);
  });
});

describe("a task's trail on a state level", () => {
  it("lists each body the task moved to in the events, in order, naming the primary's state while it is on the primary", () => {
    const scene = build(inProgressSky(), { kind: "state", id: "in_progress" });

    expect(scene.hostTrail!("PROJ-1")).toEqual([{ at: 800, host: "in-progress#worktree_ready" }, { at: 900, host: "triaging-cr-reviews" }, { at: 980, host: "in-progress#worktree_ready" }]);
  });
});

describe("a Board state's sun", () => {
  const sized = (counts: Record<string, number> = {}) => build(withTasks(boardSky(), counts), { kind: "board" }).galaxies;

  it("is at least the least size, whatever its live tasks, and grows only for its own text", () => {
    const quiet = sized();
    const busy = sized({ new: 5, ready: 80, review: 120, done: 3000 });

    for (const g of [quiet, busy]) for (const id of Object.keys(g)) expect(g[id].r).toBeGreaterThanOrEqual(SUN_R);
    // each sun holds its own name and count, so the suns are not all one size
    for (const g of [quiet, busy]) expect(new Set(Object.values(g).map((x) => x.r)).size).toBeGreaterThan(1);
  });
  it("is the least size on the state's own level, whatever the Board's suns grew to hold their names", () => {
    const sky = withTasks(boardSky(), { done: 400 });

    expect(build(sky, { kind: "state", id: "done" }).sun!.r).toBe(SUN_R);
    expect(build(sky, { kind: "board" }).galaxies.done.r).toBeGreaterThanOrEqual(SUN_R);
  });
});

describe("a flow shared by two Board states", () => {
  // `ci` opens under In Progress and under Review; each machine task names the Board task it works.
  const shared = () => {
    const snap: Snapshot = {
      graphs: ["board", "ci", "runs"],
      flows: [
        { name: "board", machine: machine(["ready", "in_progress", "review"], { submachines: [
          { state: "in_progress", machine: "ci", exits: {}, parent: "board", when: "a PR is open" },
          { state: "review", machine: "ci", exits: {}, parent: "board", when: "a PR is open" },
        ] }), agents: [
          { id: "T-1", title: "a", state: "in_progress", model: "", labels: [] },
          { id: "T-2", title: "b", state: "review", model: "", labels: [] },
          { id: "T-3", title: "c", state: "review", model: "", labels: [] },
        ] },
        { name: "ci", machine: machine(["opened", "running"]), agents: [
          { id: "ci-1", task: "T-1", title: "a", state: "running", model: "", labels: [] },
          { id: "ci-2", task: "T-2", title: "b", state: "running", model: "", labels: [] },
          { id: "ci-3", task: "T-3", title: "c", state: "opened", model: "", labels: [] },
        ] },
      ],
      dags: [], settled: {}, error: null, now: 1000,
    };
    const S = merge(snap), moves = new Moves();
    moves.observe(S, 1000);
    return { S, moves, W: 1670, H: 1080, T: 1000 };
  };
  const level: Level = { kind: "machine", flow: "ci" };
  const ids = (host?: string) => build({ ...shared(), host }, level).machineTasks.map((t) => t.task).sort();

  it("draws at each host only the tasks that sit in that Board state", () => {
    expect(ids("in_progress")).toEqual(["T-1"]);
    expect(ids("review")).toEqual(["T-2", "T-3"]);
  });

  it("counts a machine state's tasks from the host's tasks alone", () => {
    const at = (host: string) => Object.fromEntries(Object.values(build({ ...shared(), host }, level).mStates).map((s) => [s.id, s.n]));
    expect(at("in_progress")).toEqual({ opened: 0, running: 1 });
    expect(at("review")).toEqual({ opened: 1, running: 1 });
  });

  it("draws every task when no host is named", () => {
    expect(ids()).toEqual(["T-1", "T-2", "T-3"]);
  });

  it("sizes the flow's moon on each host by that host's tasks", () => {
    const orbiting = (state: string) => build(shared(), { kind: "state", id: state }).planets.find((p) => p.name === "ci")?.n;
    expect([orbiting("in_progress"), orbiting("review")]).toEqual([1, 2]);
  });
});
