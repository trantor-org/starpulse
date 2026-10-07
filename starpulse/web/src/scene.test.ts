import { describe, expect, it } from "vitest";
import { bez, BOARD_GROW, build, GALAXY_MAX, GALAXY_MIN, Drawn, routed, clip, curveDist, MIN_PAGE, glyph, nearestWithin, paged, rings, sample, stateR, taskSlot, tethersDrawn, terminal, textW, turnPage, type BEdge, type Curve, type MState, type Pt, type Scene } from "./scene";
import { drill, ledgerLevel, type Level } from "./levels";
import { merge, Moves } from "./sky";
import type { Cue, Dag, LedgerRow, Machine, Snapshot } from "./types";

const dag = (name: string, steps: [string, string[]][] = []): Dag => ({
  name, status: "succeeded", runId: "r", startedAt: "", finishedAt: "",
  steps: steps.map(([n, depends]) => ({ name: n, depends, status: "succeeded" })),
});
const machine = (ids: string[], extra: Partial<Machine> = {}): Machine => ({
  states: ids.map((id, i) => ({ id, name: id, initial: i === 0, final: false })),
  transitions: [],
  ...extra,
});
const sky = () => {
  const snap: Snapshot = {
    graphs: ["board", "in-progress", "triaging-cr-reviews", "runs"],
    flows: [
      { name: "board", agents: [{ id: "PROJ-1", title: "t", state: "ready", model: "", labels: [] }], machine: machine(["ready", "in_progress", "review"], {
        transitions: [{ source: "ready", target: "in_progress", event: "CLAIM" }, { source: "in_progress", target: "review", event: "REVIEW" }],
        subflows: [{ state: "in_progress", flow: "in-progress", exits: {}, parent: "board", when: "" }],
        writers: { CLAIM: [{ actor: "board-autopilot", trigger: "dagu" }] },
      }) },
      { name: "in-progress", agents: [], machine: machine(["worktree_ready", "pr_opened"], {
        transitions: [{ source: "worktree_ready", target: "pr_opened", event: "PR_OPENED" }],
        subflows: [{ state: "pr_opened", flow: "triaging-cr-reviews", exits: {}, parent: "in-progress", when: "a PR is open" }],
      }) },
      { name: "triaging-cr-reviews", agents: [], machine: machine(["fetch", "reply"]) },
    ],
    dags: [dag("board-autopilot", [["claim", []]]), dag("worktree-reap", [["list", []], ["reap", ["list"]]])],
    domains: [{ name: "Board", dags: [{ name: "board-autopilot", runSafe: false }, { name: "worktree-reap", runSafe: true }] }],
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
  const st = (final: boolean, mini?: boolean): MState => ({ id: "s", name: "S", final, initial: false, flow: "f", n: 4, color: "#fff", mini, loops: [], x: 0, y: 0 });
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
const boardSky = ({ writes = {}, cues = [], launches = [], free = {}, ledgers }: { writes?: Record<string, string[]>; cues?: Cue[]; launches?: string[]; free?: Record<string, string[]>; ledgers?: Record<string, LedgerRow[]> } = {}) => {
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
        subflows: [{ state: "in_progress", flow: "in-progress", exits: {}, parent: "board", when: "" }],
        launches: Object.fromEntries(launches.map((d) => [d, { skill: "delivering", flow: "in-progress" }])),
        writers, dagActors: Object.keys(writes), mainLine: ["new", "ready", "in_progress", "review", "done"],
      }) },
      { name: "in-progress", agents: [], machine: machine(["worktree_ready", "pr_opened"]) },
    ],
    dags: [...tied, ...loose].map((n) => dag(n, [["run", []]])),
    domains: [{ name: "Board", dags: tied.map((name) => ({ name, runSafe: false })) }, ...Object.entries(free).map(([name, dags]) => ({ name, dags: dags.map((d) => ({ name: d, runSafe: false })) }))],
    cues, ledgers, settled: {}, error: null, now: 1000,
  };
  const S = merge(snap), moves = new Moves();
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
const middle = (e: BEdge) => bez(e.p0!, e.c!, e.p1!, 0.5);

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
  it("orbits no arrival on a starting state, since each is drawn where it is now, yet sizes the state by them", () => {
    const sky = today(), scene = build(sky, { kind: "board" }), sun = build(sky, { kind: "state", id: "new" });
    const none = boardSky(), empty = build(none, { kind: "board" });

    expect([scene.tasks.filter((k) => k.host === scene.galaxies.new).length, sun.tasks.length]).toEqual([0, 0]);
    expect([sun.sun!.n, sun.sun!.today]).toEqual([2, 2]);
    expect(scene.galaxies.new.r).toBeGreaterThan(empty.galaxies.new.r);
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
  it("counts and orbits them on a terminal state's own level too", () => {
    const sun = build(today(), { kind: "state", id: "done" });

    expect([sun.sun!.n, sun.sun!.today, sun.tasks.map((k) => k.id)]).toEqual([3, 3, ["PROJ-3", "PROJ-4", "PROJ-5"]]);
  });
});

describe("a Board state's sun", () => {
  it("carries the state's final flag, so a terminal state's level draws a black hole rather than a sun", () => {
    const sky = boardSky();
    sky.S.flows.board.machine.states.find((s) => s.id === "done")!.final = true;
    expect(build(sky, { kind: "state", id: "done" }).sun!.final).toBe(true);
    expect(build(sky, { kind: "state", id: "review" }).sun!.final).toBe(false);
  });
  it("grows with the state's tasks, as the state does on the Board", () => {
    const sky = withTasks(boardSky(), { done: 400, review: 10 }), board = build(sky, { kind: "board" });
    const done = build(sky, { kind: "state", id: "done" }).sun!, review = build(sky, { kind: "state", id: "review" }).sun!;

    expect(done.r).toBeGreaterThan(review.r);
    expect([done.r, review.r]).toEqual([board.galaxies.done.r, board.galaxies.review.r]);
  });
});

describe("a Board state's size", () => {
  it("grows with its tasks from a fixed minimum, and to hold them in one ring, up to a fixed maximum", () => {
    const sizes = (counts: Record<string, number>) => build(withTasks(boardSky(), counts), { kind: "board" }).galaxies;
    const g = sizes({ new: 20, ready: 60, review: 80, done: 3000 });

    expect(g.in_progress.r / 1.25).toBe(sizes({}).new.r);
    expect(g.new.r).toBeLessThan(g.ready.r);
    expect(g.ready.r).toBeLessThan(g.review.r);
    expect(g.review.r).toBeLessThan(g.done.r);
    expect([g.done.r, sizes({ done: 6000 }).done.r, sizes({ in_progress: 3000 }).in_progress.r]).toEqual([140, 140, 175]);
  });
});

describe("a Board laid out at the values it shows", () => {
  it("carries each state's radius and place, and the sky's width, as the renderer eases them", () => {
    const sky = withTasks(boardSky(), { ready: 150, done: 400 }), full = build(sky, { kind: "board" });
    const shown = build({ ...sky, ease: (key: string, v: number) => (key.endsWith(".r") ? v / 2 : key === "done.x" ? v + 100 : key === "sky.w" ? v + 50 : v) }, { kind: "board" });

    for (const id of Object.keys(full.galaxies)) expect(shown.galaxies[id].r).toBeCloseTo(full.galaxies[id].r / 2);
    expect(shown.galaxies.done.x).toBeCloseTo(full.galaxies.done.x + 100);
    expect(shown.w).toBeCloseTo(full.w + 50);
    expect(build({ ...sky, ease: (_key: string, v: number) => v / 2 }, { kind: "state", id: "done" }).sun!.r).toBeCloseTo(full.galaxies.done.r / 2);
  });
  it("eases a state's ring of machines and each machine's place on it, so a machine row growing moves them instead of snapping", () => {
    const sky = withTasks(boardSky(), { in_progress: 40 }), full = build(sky, { kind: "board" });
    const shown = build({ ...sky, ease: (key: string, v: number) => (key.endsWith(".moonR") ? v + 30 : key.endsWith(".dx") ? v + 10 : v) }, { kind: "board" });

    expect(full.moons.length).toBeGreaterThan(0);
    expect(shown.galaxies.in_progress.moonR).toBeCloseTo(full.galaxies.in_progress.moonR + 30);
    for (const [i, m] of shown.moons.entries()) if (!m.pager) expect(m.x).toBeCloseTo(full.moons[i].x + 10);
  });
  it("eases each state's reach, where its paths end, so a new ring of tasks moves the ends instead of snapping them", () => {
    const sky = withTasks(boardSky(), { ready: 150, done: 400 }), full = build(sky, { kind: "board" });
    const shown = build({ ...sky, ease: (key: string, v: number) => (key.endsWith(".R") ? v + 30 : v) }, { kind: "board" });

    for (const id of Object.keys(full.galaxies)) expect(shown.galaxies[id].R).toBeCloseTo(full.galaxies[id].R + 30);
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
      expect(Math.hypot(e.p0.x - a.x, e.p0.y - a.y)).toBeCloseTo(a.R, 6);
      expect(Math.hypot(e.p1.x - b.x, e.p1.y - b.y)).toBeCloseTo(b.R, 6);
    }
  });
});

describe("a Board path's route", () => {
  // New and Done on one row with Ready between them, so the straight path from New to Done runs through Ready
  const at = (id: string, x: number, y: number, R: number) => ({ id, x, y, R }) as unknown as Parameters<typeof routed>[0];
  const sky = { x: 800, y: 600 }, a = at("new", 100, 300, 30), b = at("done", 700, 300, 30), c0 = { x: 400, y: 300 };

  it("keeps the bend it held while that bend still clears, rather than hopping to another spot the search would pick", () => {
    const o = at("ready", 400, 300, 40), first = routed(a, b, c0, [a, b, o], new Drawn(), sky);
    const held = { x: first.c.x, y: 600 - first.c.y }; // the same bend on the other side clears as well

    expect(routed(a, b, c0, [a, b, o], new Drawn(), sky, held).c).toEqual(held);
  });
  it("is held from one Board to the next through the bends the renderer keeps, each in the frame of its two states", () => {
    // Ready → Done runs along the main line through In progress and Review, so it bends round them
    const sky = withTasks(boardSky(), { ready: 150, done: 400 }), routes = new Map<string, Pt>();
    sky.S.flows.board.machine.transitions.push({ source: "ready", target: "done", event: "SKIP" });
    build({ ...sky, routes }, { kind: "board" });
    expect(routes.size).toBeGreaterThan(0);

    const [k, h] = [...routes][0], nudged = new Map([[k, { x: h.x + 0.01, y: h.y }]]), [source, target] = k.split(">");
    const scene = build({ ...sky, routes: nudged }, { kind: "board" }), e = scene.bEdges.find((x) => x.source === source && x.target === target)!;
    const A = scene.galaxies[source], B = scene.galaxies[target], dx = B.x - A.x, dy = B.y - A.y;
    expect([e.c!.x, e.c!.y]).toEqual([expect.closeTo(A.x + (h.x + 0.01) * dx - h.y * dy, 6), expect.closeTo(A.y + (h.x + 0.01) * dy + h.y * dx, 6)]);
  });
  it("straightens a bent path only once the straight path clears by a margin, so a state's size crossing the line never flips it back and forth", () => {
    const held = { x: 400, y: 120 }, by = (gap: number) => at("ready", 400, 300 + 40 + 20 + gap, 40);

    expect(routed(a, b, c0, [a, b, by(4)], new Drawn(), sky).c).toEqual(c0);
    expect(routed(a, b, c0, [a, b, by(4)], new Drawn(), sky, held).c).toEqual(held);
    expect(routed(a, b, c0, [a, b, by(30)], new Drawn(), sky, held).c).toEqual(c0);
  });
});

describe("a Board DAG's tether", () => {
  it("runs to the middle of the path carrying most of its criteria, and its hover lists every criterion", () => {
    const scene = build(boardSky({ writes: { multi: ["REVIEW", "MERGED"] }, cues: [cue("multi", "REVIEW", "review")] }), { kind: "board" }), t = scene.stars.multi.tether!;

    expect(t.edge).toBe(edgeOf(scene, "REVIEW"));
    expect([t.x, t.y]).toEqual([middle(t.edge!).x, middle(t.edge!).y]);
    expect(t.crit).toEqual(["writes REVIEW (in_progress → review)", "writes MERGED (review → done)", "runs on each merge, beside REVIEW (in_progress → review)"]);
  });

  it("breaks a tie toward the path whose two states its criteria touch most", () => {
    const scene = build(boardSky({ writes: { chain: ["CLAIM", "REVIEW", "MERGED"] } }), { kind: "board" });

    // In Progress and Review each carry two of its criteria, so the path between them outranks Ready → In Progress and Review → Done
    expect(scene.stars.chain.tether!.edge).toBe(edgeOf(scene, "REVIEW"));
  });

  it("rides a cue on the path of the event it runs beside, fainter than a writer's", () => {
    const scene = build(boardSky({ cues: [cue("graph-refresh", "MERGED", "done")] }), { kind: "board" }), t = scene.stars["graph-refresh"].tether!;

    expect(t.edge).toBe(edgeOf(scene, "MERGED"));
    expect([t.cue, t.crit]).toEqual([true, ["runs on each merge, beside MERGED (review → done)"]]);
  });

  it("finds a merged path by any event on it, and names each criterion by its own event", () => {
    const sky = boardSky({ writes: { second: ["SHIP"] }, cues: [cue("second", "SHIP", "review")] });
    sky.S.flows.board.machine.transitions.push({ source: "in_progress", target: "review", event: "SHIP" });
    const scene = build(sky, { kind: "board" }), t = scene.stars.second.tether!;

    expect(t.edge!.events).toEqual(["REVIEW", "SHIP"]);
    expect(t.crit).toEqual(["writes SHIP (in_progress → review)", "runs on each merge, beside SHIP (in_progress → review)"]);
  });

  it("never puts the tether on a self-transition, and falls back to the state when that is all it writes", () => {
    const scene = build(boardSky({ writes: { loopy: ["STAY", "CLAIM"], stayer: ["STAY"] } }), { kind: "board" });

    expect(scene.stars.loopy.tether!.edge).toBe(edgeOf(scene, "CLAIM"));
    expect(scene.stars.loopy.tether!.crit).toHaveLength(2);
    expect([scene.stars.stayer.tether!.edge, scene.stars.stayer.tether!.g]).toEqual([undefined, scene.galaxies.in_progress]);
    expect(scene.stars.stayer.tether!.crit).toEqual(["writes STAY (in_progress)"]);
  });
});

describe("DAG folds on the Board", () => {
  it("folds two DAGs that write one path into one body that lists each with its criteria", () => {
    const scene = build(boardSky({ writes: { alpha: ["CLAIM"], beta: ["CLAIM"], solo: ["MERGED"] } }), { kind: "board" }), f = scene.stars["fold:ready>in_progress"];

    expect([f.name, f.fold]).toEqual(["2 DAGs", ["alpha", "beta"]]);
    expect(f.tether!.crit).toEqual(["alpha: writes CLAIM (ready → in_progress)", "beta: writes CLAIM (ready → in_progress)"]);
    expect(f.tether!.edge).toBe(edgeOf(scene, "CLAIM"));
    expect([scene.stars.alpha, scene.stars.beta]).toEqual([undefined, undefined]);
    expect(scene.stars.solo.fold).toBeUndefined();
  });

  it("folds DAGs with no path by the state they sit beside, and a fold of cues stays a cue tether", () => {
    const scene = build(boardSky({ writes: { one: ["STAY"], two: ["STAY"] }, cues: [cue("c1", "MERGED", "done"), cue("c2", "MERGED", "done")] }), { kind: "board" });

    expect(scene.stars["fold:in_progress"].fold).toEqual(["one", "two"]);
    expect(scene.stars["fold:in_progress"].tether!.g).toBe(scene.galaxies.in_progress);
    expect(scene.stars["fold:review>done"].tether!.cue).toBe(true);
  });

  it("draws a fold as a fan of up to three steps, one per DAG", () => {
    const scene = build(boardSky({ writes: { a: ["CLAIM"], b: ["CLAIM"], c: ["CLAIM"], d: ["CLAIM"] } }), { kind: "board" }), f = scene.stars["fold:ready>in_progress"];

    expect([f.name, f.glyph.nodes.map((n) => n.name)]).toEqual(["4 DAGs", ["a", "b", "c"]]);
  });
});

describe("tethers are hover-only", () => {
  const scene = build(boardSky({ writes: { alpha: ["CLAIM"], beta: ["CLAIM"], solo: ["REVIEW"] }, cues: [cue("graph-refresh", "MERGED", "done")] }), { kind: "board" });

  it("draws none at rest and exactly the hovered DAG's one while it is hovered", () => {
    expect(tethersDrawn(scene, null)).toEqual([]);
    expect(tethersDrawn(scene, scene.stars.solo).map(([s, t]) => [s.name, t])).toEqual([["solo", scene.stars.solo.tether]]);
    expect(tethersDrawn(scene, scene.stars["fold:ready>in_progress"])).toHaveLength(1);
  });
});

describe("the DAGs free of the Board", () => {
  const fixture = () => boardSky({ writes: { w: ["CLAIM"] }, cues: [cue("q", "MERGED", "done")], launches: ["pr-launcher"], free: { Ops: ["free-a", "free-b"], Docs: ["free-c"] } });

  it("leaves every DAG that writes no lane and is no cue off the Board, launchers included", () => {
    const scene = build(fixture(), { kind: "board" });

    expect(Object.keys(scene.stars).sort()).toEqual(["q", "w"]);
  });

  it("folds them into one DAGs body at the right end of the axis, opposite New", () => {
    const scene = build(fixture(), { kind: "board" }), h = scene.hangar!, xs = Object.values(scene.galaxies).map((g) => g.x);

    expect([h.names, h.doms]).toEqual([["pr-launcher", "free-a", "free-b", "free-c"], 3]);
    expect([h.x > Math.max(...xs), h.y]).toEqual([true, scene.galaxies.new.y]);
  });

  it("keeps the hangar clear of a final state that ends the axis", () => {
    const snap: Snapshot = {
      graphs: ["board", "runs"],
      flows: [{ name: "board", agents: [], machine: {
        ...machine(["to_do", "in_progress", "done"], { transitions: [{ source: "to_do", target: "in_progress", event: "START" }, { source: "in_progress", target: "done", event: "FINISH" }], mainLine: ["to_do", "in_progress", "done"] }),
        states: [{ id: "to_do", name: "To Do", initial: true, final: false }, { id: "in_progress", name: "In Progress", initial: false, final: false }, { id: "done", name: "Done", initial: false, final: true }],
      } }],
      dags: ["free-a", "free-b"].map((n) => dag(n, [["run", []]])),
      domains: [{ name: "Ops", dags: [{ name: "free-a", runSafe: false }, { name: "free-b", runSafe: false }] }],
      cues: [], settled: {}, error: null, now: 1000,
    };
    const S = merge(snap), moves = new Moves();
    moves.observe(S, 1000);
    const scene = build({ S, moves, W: 1920, H: 1080, T: 1000 }, { kind: "board" }), h = scene.hangar!, done = scene.galaxies.done;

    expect(h.x - h.r).toBeGreaterThanOrEqual(done.x + done.reach[0]);
  });

  it("draws no hangar when every DAG is tied to the Board", () => {
    expect(build(boardSky({ writes: { w: ["CLAIM"] } }), { kind: "board" }).hangar).toBeUndefined();
  });
});

describe("the DAGs level", () => {
  const long = (p: string, n: number) => Array.from({ length: n }, (_, i) => `${p}-a-rather-long-dag-name-${String(i).padStart(2, "0")}`);
  const rowsOf = (scene: Scene, name: string) => new Set(scene.groups.find((g) => g.name === name)!.stars.map((s) => s.y)).size;

  it("lays out only the free DAGs, one block per domain in name order", () => {
    const scene = build(boardSky({ writes: { w: ["CLAIM"] }, launches: ["pr-launcher"], free: { Ops: ["free-a", "free-b"] } }), { kind: "dags" });

    expect(Object.keys(scene.stars).sort()).toEqual(["free-a", "free-b", "pr-launcher"]);
    expect(scene.groups.map((g) => [g.name, g.stars.map((s) => s.name)])).toEqual([["Board", ["pr-launcher"]], ["Ops", ["free-a", "free-b"]]]);
  });

  // One row count R serves every block (the mockup's dock()): blocks with DAGs to spare split into R rows, and a block never has more rows
  // than DAGs, so a single-DAG block stays one row.
  it("splits every block with DAGs to spare into the same number of rows", () => {
    const scene = build(boardSky({ free: { Wide: long("w", 24), Mid: long("m", 16), Narrow: ["n-only"] } }), { kind: "dags" });

    expect(rowsOf(scene, "Wide")).toBeGreaterThan(1);
    expect(rowsOf(scene, "Mid")).toBe(rowsOf(scene, "Wide"));
    expect(rowsOf(scene, "Narrow")).toBe(1);
  });

  it("keeps each domain's DAGs in name order and inside the canvas", () => {
    const scene = build(boardSky({ free: { Wide: long("w", 24) } }), { kind: "dags" }), stars = scene.groups.find((g) => g.name === "Wide")!.stars;

    expect(stars.map((s) => s.name)).toEqual(long("w", 24));
    for (const s of stars) expect([s.x > 0, s.x < scene.w, s.y > 0, s.y < scene.h]).toEqual([true, true, true, true]);
  });

  // Several wide domains can lay out wider than the scene (the row count caps at eight), so the fit frames the stars' own box, not the scene.
  it("frames every DAG, name and domain label in its box, however many domains there are", () => {
    const named = (p: string, n: number) => Array.from({ length: n }, (_, i) => `${p}-dag-${String(i).padStart(2, "0")}`);
    const free = { A: named("delivery", 9), B: named("board", 3), C: named("agent-job", 10), D: named("retrieval", 8), E: named("host-ops", 10), Stress: named("machine", 40) };
    const scene = build(boardSky({ free }), { kind: "dags" }), [x0, y0, x1, y1] = scene.box!;

    for (const s of Object.values(scene.stars)) expect([s.x - s.glyph.w / 2 >= x0, s.x + s.glyph.w / 2 <= x1, s.y - s.glyph.h / 2 >= y0, s.y + s.glyph.h / 2 <= y1]).toEqual([true, true, true, true]);
    for (const g of scene.groups) expect([g.lx >= x0, g.lx <= x1, g.ly >= y0]).toEqual([true, true, true]);
    // the scene widens until the blocks fit it, so the names keep the room their widths were laid out for
    expect(x1 - x0).toBeLessThanOrEqual(scene.w);
  });
});

// The saved design snapshot's Board (the design mockup): ten states and their transitions, in declaration order.
const SAVED_STATES = ["new", "ready", "blocked", "waiting", "in_progress", "review", "needs_attention", "done", "completed", "archived"];
const SAVED_TRANSITIONS = `new>ready new>blocked new>waiting new>in_progress ready>in_progress ready>blocked ready>waiting ready>archived
  blocked>blocked blocked>ready blocked>in_progress blocked>archived waiting>ready waiting>in_progress waiting>archived in_progress>blocked
  in_progress>in_progress in_progress>review in_progress>done in_progress>needs_attention in_progress>archived review>done review>in_progress
  review>archived needs_attention>ready needs_attention>in_progress needs_attention>archived done>completed`.split(/\s+/).map((t) => t.split(">"));
const savedBoardSky = (W: number, H: number, patch: (snap: Snapshot) => void = () => {}) => {
  const snap: Snapshot = {
    graphs: ["board"],
    flows: [{ name: "board", agents: [], machine: {
      states: SAVED_STATES.map((id, i) => ({ id, name: id, initial: i === 0, final: id === "completed" || id === "archived" })),
      transitions: SAVED_TRANSITIONS.map(([source, target]) => ({ source, target, event: `${source}_${target}` })),
      mainLine: ["new", "ready", "in_progress", "review", "done"],
    } }],
    dags: [], domains: [], settled: {}, error: null, now: 1000,
  };
  patch(snap);
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W, H, T: 1000 };
};
/** The distance from a point to the nearest sample of a path. */
const clearance = (e: Curve, g: Pt & { R: number }) => Math.min(...sample(e, 200).map((q) => Math.hypot(q.x - g.x, q.y - g.y))) - g.R;

describe("the Board layout", () => {
  const MAIN = ["new", "ready", "in_progress", "review", "done"];
  const placed = (W = 1920, H = 1080) => build(savedBoardSky(W, H), { kind: "board" }).galaxies;

  it("sits the main line on one axis in the order the snapshot declares", () => {
    const g = placed();

    expect(new Set(MAIN.map((id) => g[id].y)).size).toBe(1);
    MAIN.slice(1).forEach((id, i) => expect(g[id].x).toBeGreaterThan(g[MAIN[i]].x));
  });

  it("takes each other open state's slot just before the latest main-line state it connects to, alternating above and below the axis", () => {
    const g = placed(), axis = g.new.y, before = ["blocked", "waiting", "needs_attention"];

    before.forEach((id) => {
      expect(g[id].x).toBeCloseTo(g.blocked.x);
      expect(g[id].x).toBeGreaterThan(g.ready.x);
      expect(g[id].x).toBeLessThan(g.in_progress.x);
    });
    expect([g.blocked.y < axis, g.waiting.y > axis, g.needs_attention.y < axis]).toEqual([true, true, true]);
    expect(g.needs_attention.y).toBeLessThan(g.blocked.y);
  });

  it("puts final states one slot past the axis, one above it and one below, and closes the empty slots", () => {
    const g = placed(), gap = (a: string, b: string) => g[b].x - g[a].x;

    expect(g.completed.x).toBeCloseTo(g.archived.x);
    expect(g.completed.x).toBeGreaterThan(g.done.x);
    expect([g.completed.y < g.new.y, g.archived.y > g.new.y]).toEqual([true, true]);
    // slots 1, 5 and 7 hold nothing, so Ready sits one slot after New and the slot before Review is Review's own neighbour
    expect(gap("new", "ready")).toBeCloseTo(gap("ready", "blocked"));
    expect(gap("in_progress", "review")).toBeCloseTo(gap("review", "done"));
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
  const crowd = (W: number, H: number, counts: Record<string, number>) => savedBoardSky(W, H, (snap) => {
    snap.flows[0].agents = Object.entries(counts).flatMap(([state, n]) => Array.from({ length: n }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
  });

  it.each([
    ["the base Board", 1920, 1080, {}],
    ["a busy Board", 1920, 1080, crowdedCounts],
    ["a stressed Board", 1670, 1080, Object.fromEntries(SAVED_STATES.map((s) => [s, 90]))],
  ])("pass no state but their own two within 17 px on %s", (_, W, H, counts) => {
    const scene = build(crowd(W, H, counts), { kind: "board" }), close: string[] = [];

    for (const e of scene.bEdges)
      for (const g of Object.values(scene.galaxies))
        if (g.id !== e.source && g.id !== e.target && clearance(e as Curve, g) < 17) close.push(`${e.source}>${e.target} by ${g.id}`);
    expect(close).toEqual([]);
  });

  it("gather into one stream along a final state's side when it is reached from several states", () => {
    // New, Ready and Done on the axis; Archived is reached from all three, with nothing in their way
    const sky = savedBoardSky(1920, 1080, (snap) => {
      const m = snap.flows[0].machine;
      m.states = ["new", "ready", "done", "archived"].map((id, i) => ({ id, name: id, initial: i === 0, final: id === "archived" }));
      m.transitions = [["new", "ready"], ["ready", "done"], ["new", "archived"], ["ready", "archived"], ["done", "archived"]].map(([source, target]) => ({ source, target, event: `${source}_${target}` }));
      m.mainLine = ["new", "ready", "done"];
    }), scene = build(sky, { kind: "board" }), into = scene.bEdges.filter((e) => e.target === "archived");

    expect(into).toHaveLength(3);
    for (const e of into) expect(e.c!.y).toBeCloseTo(scene.galaxies.archived.y);
  });

  it("bow to opposite sides when a pair is joined both ways, and run straight when it is one way", () => {
    const scene = build(savedBoardSky(1920, 1080), { kind: "board" }), mid = (e: Curve) => ({ x: (e.p0.x + e.p1.x) / 2, y: (e.p0.y + e.p1.y) / 2 });
    const edge = (s: string, t: string) => scene.bEdges.find((e) => e.source === s && e.target === t) as unknown as Curve;
    const off = (e: Curve) => Math.hypot(e.c.x - mid(e).x, e.c.y - mid(e).y);

    expect(off(edge("review", "in_progress"))).toBeGreaterThan(1);
    expect(off(edge("in_progress", "review"))).toBeGreaterThan(1);
    expect(off(edge("new", "ready"))).toBeLessThan(1);
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
    for (const a of gs) for (const b of gs) if (a.x < b.x && Math.abs(a.y - b.y) < a.R + b.R + 40 && b.x - b.R - (a.x + a.R) < 40 - 1e-6) short.push(`${a.id}/${b.id}`);
    return short;
  };
  const busy = (patch: (snap: Snapshot) => void = () => {}) => savedBoardSky(1920, 1080, (snap) => {
    snap.flows[0].agents = Object.entries({ ready: 90, waiting: 60, in_progress: 40, done: 90, review: 20 }).flatMap(([state, n]) => Array.from({ length: n }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
    patch(snap);
  });

  it("holds 40 px between a state's tasks and the next state beside it", () => {
    expect(apart(build(busy(), { kind: "board" }))).toEqual([]);
  });

  it("widens the sky to keep the canvas's shape when the states need more room", () => {
    const scene = build(busy(), { kind: "board" });

    expect(scene.w / scene.h).toBeCloseTo(1920 / 1080, 1);
  });

  it("leaves room on a path for the DAG body that writes it, wider for a fold of several", () => {
    const wide = dag("wide-dag-with-a-long-name", [["a", []], ["b", ["a"]], ["c", ["b"]], ["d", ["c"]]]);
    const writers = (n: number) => (snap: Snapshot) => {
      snap.flows[0].machine.writers = { ready_in_progress: Array.from({ length: n }, (_, i) => ({ actor: i ? `dag-${i}` : wide.name, trigger: "dagu" })) };
      snap.dags = [wide, ...Array.from({ length: n - 1 }, (_, i) => dag(`dag-${i + 1}`))];
    };
    const gap = (scene: ReturnType<typeof build>) => scene.galaxies.in_progress.x - scene.galaxies.in_progress.R - (scene.galaxies.ready.x + scene.galaxies.ready.R);
    const one = build(busy(writers(1)), { kind: "board" }), fold = build(busy(writers(3)), { kind: "board" });

    expect(gap(one)).toBeGreaterThanOrEqual(40 + glyph(wide).w);
    expect(gap(fold)).toBeGreaterThanOrEqual(40 + 60);
  });
});

// The live Board's crowding: busy states, two stub launchers of one machine under In progress, and two cued DAGs, one of them wide, by Done.
describe("DAGs crowded round busy states", () => {
  const chain = (name: string, n: number) => dag(name, Array.from({ length: n }, (_, i): [string, string[]] => [`s${i}`, i ? [`s${i - 1}`] : []]));
  const wide = dag("apply-on-merge", [...Array.from({ length: 8 }, (_, i): [string, string[]] => [`c${i}`, i ? [`c${i - 1}`] : []]), ...Array.from({ length: 8 }, (_, i): [string, string[]] => [`p${i}`, ["c0"]])]);
  const crowded = (W: number, H: number, more = 0) => savedBoardSky(W, H, (snap) => {
    const board = snap.flows[0], counts: Record<string, number> = { ready: 47, waiting: 35, in_progress: 7, done: 47, review: 1, needs_attention: 4 };
    board.agents = Object.entries(counts).flatMap(([state, n]) => Array.from({ length: n }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
    board.machine.subflows = [{ state: "in_progress", flow: "running-skill-evals", exits: {}, parent: "board", when: "" }, { state: "in_progress", flow: "auditing-infrastructure", exits: {}, parent: "board", when: "" }];
    board.machine.launches = Object.fromEntries(["skill-eval", "skill-optimize"].map((d) => [d, { skill: "running-skill-evals", flow: "running-skill-evals" }]).concat([["nightly-audit", { skill: "auditing-infrastructure", flow: "auditing-infrastructure" }]]));
    board.machine.writers = { done_completed: [{ actor: "main-follow", trigger: "dagu" }] };
    snap.flows.push({ name: "running-skill-evals", agents: [], machine: machine(["fetch", "run"]) }, { name: "auditing-infrastructure", agents: [], machine: machine(["scan", "report"]) });
    for (let i = 0; i < more; i++) {
      board.machine.subflows!.push({ state: "in_progress", flow: `extra-${i}`, exits: {}, parent: "board", when: "" });
      snap.flows.push({ name: `extra-${i}`, agents: [], machine: machine(["a", "b"]) });
    }
    snap.dags = [dag("skill-eval"), dag("skill-optimize"), chain("nightly-audit", 5), chain("main-follow", 2), wide, chain("graph-refresh", 3)];
    snap.cues = [{ dag: "apply-on-merge", event: "MERGED", state: "done", on: "each merge to main" }, { dag: "graph-refresh", event: "MERGED", state: "done", on: "each merge to main" }];
  });
  const box = (s: { x: number; y: number; glyph: { w: number; h: number } }) => ({ x0: s.x - s.glyph.w / 2 - 10, y0: s.y - s.glyph.h / 2 - 10, x1: s.x + s.glyph.w / 2 + 10, y1: s.y + s.glyph.h / 2 + 10 });

  it.each([[1670, 1080, 0], [3190, 1440, 0], [1670, 1080, 20]])("keeps every DAG glyph off the other glyphs and every state at %ix%i with %i more machines under In progress", (W, H, more) => {
    const scene = build(crowded(W, H, more), { kind: "board" }), boxes = Object.values(scene.stars).map((s) => ({ name: s.name, ...box(s) }));
    const apart = (a: (typeof boxes)[number], b: (typeof boxes)[number]) => a.x1 <= b.x0 || b.x1 <= a.x0 || a.y1 <= b.y0 || b.y1 <= a.y0;
    const overlapping: string[] = [];

    boxes.forEach((a, i) => boxes.slice(i + 1).forEach((b) => { if (!apart(a, b)) overlapping.push(`${a.name}/${b.name}`); }));
    for (const a of boxes)
      for (const g of Object.values(scene.galaxies)) {
        const nx = Math.max(a.x0, Math.min(g.x, a.x1)), ny = Math.max(a.y0, Math.min(g.y, a.y1));
        if (Math.hypot(nx - g.x, ny - g.y) < g.R) overlapping.push(`${a.name}/${g.id}`);
      }
    // the two cues beside Merged fold into one body; the launchers hold no place on the Board
    expect(boxes.map((b) => b.name).sort()).toEqual(["2 DAGs", "main-follow"]);
    expect(overlapping).toEqual([]);
  });

  it.each([0, 20])("keeps every state, with its moons and their names, inside the sky with %i more machines under In progress", (more) => {
    const scene = build(crowded(1670, 1080, more), { kind: "board" });

    for (const g of Object.values(scene.galaxies)) {
      expect(g.x - g.reach[1]).toBeGreaterThanOrEqual(0);
      expect(g.x + g.reach[0]).toBeLessThanOrEqual(scene.w);
    }
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
        subflows: [{ state: "in_progress", flow: "in-progress", exits: { review_recorded: "REVIEW", needs_attention: "DEFER" }, parent: "board", when: "" }],
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

describe("the In Progress state level", () => {
  const sky = inProgressSky(), scene = build(sky, { kind: "state", id: "in_progress" });

  it("puts a task on the machine it last moved in, the primary before and after", () => {
    expect([700, 850, 950, 990].map((t) => scene.hostAt!("PROJ-1", t))).toEqual(["in-progress", "in-progress", "triaging-cr-reviews", "in-progress"]);
  });

  it("joins the primary and a skill machine by one path each way, rim to rim", () => {
    const [hub, skill] = scene.planets, dist = (a: Pt, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);
    const [out, back] = scene.hops;

    expect([hub.name, skill.name]).toEqual(["in-progress", "triaging-cr-reviews"]);
    expect([out.from, out.to, out.back, back.from, back.to, back.back]).toEqual(["in-progress", "triaging-cr-reviews", false, "triaging-cr-reviews", "in-progress", true]);
    expect(dist(out.p0, hub)).toBeCloseTo(hub.rim!);
    expect(dist(out.p1, skill)).toBeCloseTo(skill.rim!);
    expect([back.p0, back.p1]).toEqual([out.p1, out.p0]);
  });

  it("sends each exit its SUBFLOW declares to the Board state its event moves to, and enters from the state that claims it", () => {
    const declared = Object.values(sky.S.board.machine.subflows![0].exits), target = (event: string) => scene.exits.find((x) => x.event === event)?.target;

    expect(declared.map(target)).toEqual(["review", "needs_attention"]);
    expect(scene.entries.map((x) => x.source)).toEqual(["ready"]);
  });
});

describe("a machine", () => {
  it("hangs the machine that opens under a state below that state", () => {
    const scene = build(sky(), { kind: "machine", flow: "in-progress" });
    const [p] = scene.planets;

    expect([p.name, p.anchor, p.when]).toEqual(["triaging-cr-reviews", scene.mStates.pr_opened, "while a PR is open"]);
    expect(p.y).toBeGreaterThan(scene.mStates.pr_opened.y);
  });

  it("sets a crowded state's name outside its outermost ring of tasks", () => {
    const S = sky(), agents = S.S.flows["in-progress"].agents;
    for (let i = 0; i < 160; i++) agents.push({ id: `T-${i}`, title: "t", state: "pr_opened", model: "", task: `T-${i}` });
    const s = build(S, { kind: "machine", flow: "in-progress" }).mStates.pr_opened, w = textW(s.name, 12.5) / 2;
    const gap = Math.hypot(Math.max(0, Math.abs(s.lab!.x - s.x) - w), Math.max(0, Math.abs(s.lab!.y - s.y) - 9));

    expect(s.n).toBe(160);
    expect(gap).toBeGreaterThan(taskSlot(stateR(s) + 7, s.n - 1).rr + 2.8);
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
  const link = (state: string, parent: string) => ({ state, flow: "running-skill-evals", exits: {}, parent, when: "it reads" });
  // `busy` more tasks work the first twelve skills, dealt round in turn
  const extra = Array.from({ length: busy }, (_, i) => `TASK-${10 + i}`);
  const snap: Snapshot = {
    graphs: ["board", "in-progress", "triaging-cr-reviews", "running-skill-evals", ...names, "runs"],
    flows: [
      { name: "board", agents: ["PROJ-1", "PROJ-2", "PROJ-3", ...extra].map((id) => ({ id, title: "t", state: "in_progress", model: "", labels: [] })).concat([{ id: "PROJ-4", title: "t", state: "review", model: "", labels: [] }]),
        machine: machine(["ready", "in_progress", "review"], {
          transitions: [{ source: "ready", target: "in_progress", event: "CLAIM" }, { source: "in_progress", target: "review", event: "REVIEW" }],
          subflows: [{ state: "in_progress", flow: "in-progress", exits: {}, parent: "board", when: "" }],
          writers, launches: Object.fromEntries(Object.entries(launches).map(([d, flow]) => [d, { skill: "delivering", flow }])),
        }) },
      { name: "in-progress", agents: [session("PROJ-1", "pr_opened", 900), session("PROJ-3", "worktree_ready", 950)], machine: machine(["worktree_ready", "pr_opened"], {
        subflows: [{ state: "pr_opened", flow: "triaging-cr-reviews", exits: {}, parent: "in-progress", when: "a PR is open" }],
      }) },
      { name: "triaging-cr-reviews", agents: [], machine: machine(["fetch", "reply"]) },
      { name: "running-skill-evals", agents: [], machine: machine(["run", "score"]) },
      ...names.map((name, i) => ({ name, agents: [...(i ? [] : [session("PROJ-2", "writing", 980)]), ...extra.filter((_, j) => j % 12 === i).map((t) => session(t, "writing", 980))], machine: machine(["reading", "writing"], { subflows: i % 3 === 0 ? [link("reading", name)] : [] }) })),
    ],
    dags: tied.map((n) => dag(n, [["run", []]])), domains: [{ name: "Board", dags: tied.map((name) => ({ name, runSafe: false })) }], cues, settled: {}, error: null, now: 1000,
  };
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W, H, T: 1000 };
};

describe("the Board's lifecycle moons", () => {
  const board = (skills: number) => build(moonSky(skills), { kind: "board" });
  const moonsOf = (scene: ReturnType<typeof build>) => scene.moons.filter((m) => m.parent === scene.galaxies.in_progress && !m.pager);
  const side = (scene: ReturnType<typeof build>, m: { x: number }) => Math.sign(m.x - scene.galaxies.in_progress.x);
  /** The height of the row a moon and its sub-states take: the largest orbit among them, or a line of type. */
  const rowOf = (m: (typeof board extends (n: number) => infer R ? R : never)["moons"][number]) => 2 * Math.max(m.R, ...m.chain.map((b) => b.R)) + 6;

  it("sets a state's machines in rows, its primary first and the rest alternating right and left", () => {
    const scene = board(4);

    expect(moonsOf(scene).map((m) => [m.name, side(scene, m)])).toEqual([["in-progress", 1], ["skill-00", -1], ["skill-01", 1], ["skill-02", -1], ["skill-03", 1]]);
  });

  it("holds each moon on its state's dashed ring and the rows of one side apart, however many machines the state opens into", () => {
    for (const n of [2, 20]) {
      const scene = board(n), g = scene.galaxies.in_progress;

      for (const sd of [1, -1]) {
        const rows = moonsOf(scene).filter((m) => side(scene, m) === sd).sort((a, b) => a.y - b.y);
        rows.forEach((m, i) => {
          expect(Math.hypot(m.x - g.x, m.y - g.y)).toBeCloseTo(g.moonR);
          if (i) expect(m.y - rows[i - 1].y).toBeGreaterThanOrEqual((rowOf(m) + rowOf(rows[i - 1])) / 2);
        });
      }
    }
  });

  it("grows the ring and state to the fullest page instead of all twenty machines", () => {
    const base = board(2).galaxies.in_progress, stress = board(20).galaxies.in_progress;

    expect(stress.moonR).toBeGreaterThan(base.moonR);
    expect(stress.R).toBeGreaterThan(base.R);
  });

  it("chains a machine's sub-states outward from its moon on its row, and names the chain beside the machine", () => {
    const scene = board(4), g = scene.galaxies.in_progress, [primary, skill] = moonsOf(scene);

    expect([primary.chain.map((b) => b.state), skill.chain.map((b) => b.state), moonsOf(scene)[2].chain]).toEqual([["pr_opened"], ["reading"], []]);
    for (const m of [primary, skill]) {
      const b = m.chain[0], out = side(scene, m);
      expect([b.y, (b.x - m.x) * out > 0, (m.x - g.x) * out > 0]).toEqual([m.y, true, true]);
      expect(Math.abs(b.x - m.x)).toBeGreaterThanOrEqual(m.R + b.R);
      expect(b.machine).toBe(m.name);
    }
    expect([primary.label, skill.label]).toEqual(["in-progress › pr_opened", "skill-00 › reading"]);
  });

  it("puts a task in pr_opened on that sub-state and a task in a skill machine on its moon", () => {
    const scene = board(4), host = (id: string) => scene.tasks.find((t) => t.id === id)!.host, [, skill] = moonsOf(scene);

    expect(host("PROJ-1")).toBe(scene.subStates.find((b) => b.machine === "in-progress" && b.state === "pr_opened"));
    expect(host("PROJ-2")).toBe(skill);
    expect(host("PROJ-3")).toBe(scene.galaxies.in_progress);
    expect(host("PROJ-4")).toBe(scene.galaxies.review);
  });

  it("counts every task of a state on the state, wherever it orbits", () => {
    expect(board(4).galaxies.in_progress.n).toBe(3);
  });

  it("holds 40 px between a state's moon names and the next state beside it", () => {
    const scene = board(20), gs = Object.values(scene.galaxies);

    for (const a of gs) for (const b of gs) if (a.x < b.x && Math.abs(a.y - b.y) < a.R + b.R) expect(b.x - b.reach[1] - (a.x + a.reach[0])).toBeGreaterThanOrEqual(40);
  });

  it("keeps every Board state and DAG fixed while a stressed state's machine page changes", () => {
    const fixture = moonSky(20, 1920, 1080, { writes: { claimer: ["CLAIM"], reviewer: ["REVIEW"] } });
    const page = (at: number) => build({ ...fixture, pages: { in_progress: at } }, { kind: "board" });
    const first = page(0), second = page(1);
    const at = (scene: Scene) => ({
      states: Object.fromEntries(Object.entries(scene.galaxies).map(([id, g]) => [id, [g.x, g.y]])),
      dags: Object.fromEntries(Object.entries(scene.stars).map(([id, s]) => [id, [s.x, s.y]])),
    });

    expect(second.moons.map((m) => m.name)).not.toEqual(first.moons.map((m) => m.name));
    expect(first.moons.filter((m) => m.pager).map((m) => m.name)).toEqual(["‹ 2/2", "2/2 ›"]);
    expect(second.moons.filter((m) => m.pager).map((m) => m.name)).toEqual(["‹ 1/2", "1/2 ›"]);
    expect(at(second)).toEqual(at(first));
  });

  it("pages with two machine nodes on the bottom of the state's ring, back on the left and forward on the right", () => {
    const scene = board(20), g = scene.galaxies.in_progress, [back, forward] = scene.moons.filter((m) => m.pager);

    expect([back.pager!.d, forward.pager!.d, back.r, forward.r]).toEqual([-1, 1, 9, 9]);
    for (const m of [back, forward]) {
      expect(Math.hypot(m.x - g.x, m.y - g.y)).toBeCloseTo(g.moonR);
      expect(m.y).toBeGreaterThan(Math.max(...moonsOf(scene).map((o) => o.y)));
    }
    expect([back.x - g.x, back.y]).toEqual([g.x - forward.x, forward.y]);
    expect(forward.x - back.x).toBeGreaterThanOrEqual(back.R + forward.R);
  });

  it("makes each row as tall as a busy pager's orbit, as it does a machine's", () => {
    // on page two the forward node, which wins the tie, stands in for skill-00 to skill-11, which seventy-three tasks work between them
    const scene = build({ ...moonSky(20, 1920, 1080, { busy: 72 }), pages: { in_progress: 1 } }, { kind: "board" });
    const g = scene.galaxies.in_progress, pager = scene.moons.find((m) => m.pager?.d === 1)!;

    const right = moonsOf(scene).filter((m) => m.x > g.x).sort((a, b) => a.y - b.y);

    expect(pager.n).toBe(73);
    expect(pager.R).toBeGreaterThan(Math.max(...moonsOf(scene).map((m) => m.R)));
    right.forEach((m, i) => { if (i) expect(m.y - right[i - 1].y).toBeGreaterThanOrEqual(2 * pager.R + 6 - 1e-9); });
  });
});

describe("the state level's lifecycle moons", () => {
  const level = (skills: number) => build(moonSky(skills), { kind: "state", id: "in_progress" });
  const moonsOf = (scene: Scene) => scene.planets.filter((p) => p.moon && !p.pager);
  /** The quarter of the ring a moon sits in, from the primary: right or left, upper or lower. */
  const quarter = (scene: Scene, m: Pt) => [Math.sign(m.x - scene.hub!.x), Math.sign(m.y - scene.hub!.y)];

  it("sets the skill machines round the primary, alternating right and left, then upper and lower", () => {
    const scene = level(6);

    expect(scene.planets[0]).toBe(scene.hub);
    expect(moonsOf(scene).map((m) => [m.name, ...quarter(scene, m)])).toEqual([
      ["skill-00", 1, -1], ["skill-01", -1, -1], ["skill-02", 1, 1], ["skill-03", -1, 1], ["skill-04", 1, -1], ["skill-05", -1, -1],
    ]);
  });

  it("stacks each quarter's rows from the band beside the primary out to four-fifths of one ring, however many machines there are", () => {
    for (const n of [2, 20]) {
      const scene = level(n), hub = scene.hub!, moons = moonsOf(scene), ring = Math.hypot(moons[0].x - hub.x, moons[0].y - hub.y);

      for (const m of moons) {
        expect(Math.hypot(m.x - hub.x, m.y - hub.y)).toBeCloseTo(ring);
        expect(Math.abs(m.y - hub.y)).toBeGreaterThan(hub.rim! + 70);
        expect(Math.abs(m.y - hub.y)).toBeLessThanOrEqual(0.8 * ring + 1);
      }
      for (const q of [[1, -1], [-1, -1], [1, 1], [-1, 1]]) {
        const rows = moons.filter((m) => quarter(scene, m).join() === q.join()).sort((a, b) => Math.abs(a.y - hub.y) - Math.abs(b.y - hub.y));
        rows.forEach((m, i) => { if (i) expect(Math.abs(m.y - rows[i - 1].y)).toBeGreaterThanOrEqual(m.rim! + rows[i - 1].rim!); });
      }
    }
  });

  it("grows the ring until every quarter's rows fit", () => {
    const ring = (n: number) => { const s = level(n), m = moonsOf(s)[0]; return Math.hypot(m.x - s.hub!.x, m.y - s.hub!.y); };

    expect(ring(20)).toBeGreaterThan(ring(2));
  });

  // the view fits the level's frame on every snapshot, so a frame that changed with the page would move the primary on screen
  it("keeps the primary, related DAGs and the level's frame fixed while its stressed machine page changes", () => {
    const fixture = moonSky(20, 1920, 1080, { writes: { claimer: ["CLAIM"], reviewer: ["REVIEW"] } });
    const page = (at: number) => build({ ...fixture, pages: { in_progress: at } }, { kind: "state", id: "in_progress" });
    const first = page(0), second = page(1), at = (scene: Scene) => ({
      box: scene.box,
      hub: [scene.hub!.x, scene.hub!.y],
      dags: Object.fromEntries(Object.entries(scene.stars).map(([id, s]) => [id, [s.x, s.y]])),
    });

    expect(second.planets.filter((p) => p.moon).map((p) => p.name)).not.toEqual(first.planets.filter((p) => p.moon).map((p) => p.name));
    expect(first.planets.filter((p) => p.pager).map((p) => p.name)).toEqual(["‹ 2/2", "2/2 ›"]);
    expect(second.planets.filter((p) => p.pager).map((p) => p.name)).toEqual(["‹ 1/2", "1/2 ›"]);
    expect(at(second)).toEqual(at(first));
  });

  it("frames the level to what it draws, the pager nodes included, with no margin of its own", () => {
    for (const n of [2, 20]) {
      const scene = level(n), hub = scene.hub!, ring = Math.hypot(moonsOf(scene)[0].x - hub.x, moonsOf(scene)[0].y - hub.y);

      expect(scene.box![2] - hub.x).toBeLessThan(ring + 260);
      for (const p of scene.planets.filter((p) => p.pager)) expect(scene.box![3]).toBeGreaterThanOrEqual(p.y + p.rim!);
    }
  });

  it("pages with two machine nodes on the bottom of the ring, back on the left and forward on the right", () => {
    const scene = level(20), hub = scene.hub!, ring = Math.hypot(moonsOf(scene)[0].x - hub.x, moonsOf(scene)[0].y - hub.y), [back, forward] = scene.planets.filter((p) => p.pager);

    expect([back.pager!.d, forward.pager!.d, back.R, forward.R]).toEqual([-1, 1, 9, 9]);
    for (const p of [back, forward]) {
      expect(Math.hypot(p.x - hub.x, p.y - hub.y)).toBeCloseTo(ring);
      expect(p.y).toBeGreaterThan(Math.max(...moonsOf(scene).map((o) => o.y)));
    }
    expect([back.x - hub.x, back.y]).toEqual([hub.x - forward.x, forward.y]);
    expect(forward.x - back.x).toBeGreaterThanOrEqual(back.rim! + forward.rim!);
  });
});

describe("the state level's sub-state chains", () => {
  const scene = build(moonSky(4), { kind: "state", id: "in_progress" }), hub = scene.hub!;
  const moon = (name: string) => scene.planets.find((p) => p.name === name)!;
  const chainOf = (name: string) => scene.planets.filter((p) => p.subState && p.machine === name);

  it("chains a skill machine's sub-states outward from its moon along its row, and names the chain past it", () => {
    const m = moon("skill-00"), [b] = chainOf("skill-00"), out = Math.sign(m.x - hub.x);

    expect([b.state, b.flow, b.y, (b.x - m.x) * out > 0]).toEqual(["reading", "running-skill-evals", m.y, true]);
    expect(Math.abs(b.x - m.x)).toBeGreaterThanOrEqual(m.rim! + b.rim!);
    expect(m.chain).toEqual([b]);
    expect(m.label).toBe("skill-00 › reading");
  });

  it("gives a machine with no sub-state no chain and no label, and draws the primary's own sub-state as no chain", () => {
    expect([chainOf("skill-01"), moon("skill-01").label, chainOf("in-progress")]).toEqual([[], undefined, []]);
  });

  it("boxes the level past the end of the longest chain label, so no label reaches the Board paths drawn at the screen edge", () => {
    const m = moon("skill-00"), [b] = chainOf("skill-00"), [x0, , x1] = scene.box!, out = Math.sign(m.x - hub.x);
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
    const sky = moonSky(4), move = (task: string, flow: string, to: string, at: number) => ({ flow, task, at, event: "MOVE", to, from: null });
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

describe("the state level's related DAGs", () => {
  const level = (ties: Parameters<typeof moonSky>[3]) => build(moonSky(4, 1920, 1080, ties), { kind: "state", id: "in_progress" });
  const radii = (scene: Scene) => Array.from({ length: 8 }, (_, i) => scene.hub!.rim! + 150 + 95 * i);
  const from = (scene: Scene, s: Pt) => Math.hypot(s.x - scene.hub!.x, s.y - scene.hub!.y);

  it("holds each DAG tied to the state still on a ring round the primary, the first straight above it, and lists its ties on hover", () => {
    const scene = level({ writes: { claimer: ["CLAIM"], reviewer: ["REVIEW"] }, cues: [{ dag: "refresher", event: "REVIEW", state: "in_progress", on: "each merge" }], launches: { delivering: "in-progress" } });
    const stars = ["claimer", "delivering", "refresher", "reviewer"].map((n) => scene.stars[n]), [first] = stars;

    for (const s of stars) expect(radii(scene).some((r) => Math.abs(from(scene, s) - r) < 0.5)).toBe(true);
    expect([first.x, first.y]).toEqual([scene.hub!.x, scene.hub!.y - radii(scene)[0]]);
    expect(scene.stars.claimer.tether!.crit).toEqual(["writes CLAIM (ready → in_progress)"]);
    expect(scene.stars.delivering.tether!.crit).toEqual(["launches in-progress"]);
    expect(scene.stars.refresher.tether).toMatchObject({ cue: true, crit: ["runs on each merge, beside REVIEW"] });
    expect(scene.groups.flatMap((g) => g.stars)).toHaveLength(4);
  });

  it("gives every DAG a place that clears the Board paths, the moons and the others, taking the next ring out when one is full", () => {
    const cues: Cue[] = Array.from({ length: 24 }, (_, i) => ({ dag: `cued-${String(i).padStart(2, "0")}`, event: "REVIEW", state: "in_progress", on: `run ${i}` })), scene = level({ cues });
    const stars = cues.map((c) => scene.stars[c.dag]), hub = scene.hub!, moons = scene.planets.filter((p) => p.moon);

    for (const [i, s] of stars.entries()) {
      expect(radii(scene).some((r) => Math.abs(from(scene, s) - r) < 0.5)).toBe(true);
      expect(Math.abs(Math.sin(Math.atan2(s.y - hub.y, s.x - hub.x)))).toBeGreaterThan(Math.sin((26 * Math.PI) / 180)); // not on the Board paths' left and right bands
      for (const o of stars.slice(i + 1)) expect(Math.hypot(s.x - o.x, s.y - o.y)).toBeGreaterThan(40);
      for (const m of moons) expect(Math.hypot(s.x - m.x, s.y - m.y)).toBeGreaterThan(m.rim! + 12);
    }
    expect(new Set(stars.map((s) => Math.round(from(scene, s)))).size).toBeGreaterThan(1);
  });

  it("folds DAGs with the same ties into one body, as on the Board", () => {
    const scene = level({ writes: { a: ["CLAIM"], b: ["CLAIM"], c: ["REVIEW"] } }), key = Object.keys(scene.stars).find((k) => k.startsWith("fold:"))!;

    expect(Object.keys(scene.stars).sort()).toEqual(["c", key]);
    expect([scene.stars[key].name, scene.stars[key].fold]).toEqual(["2 DAGs", ["a", "b"]]);
    expect(scene.stars[key].tether!.crit).toEqual(["a: writes CLAIM (ready → in_progress)", "b: writes CLAIM (ready → in_progress)"]);
  });
});

describe("the state level's launch-only DAGs", () => {
  const scene = build(moonSky(4, 1920, 1080, { writes: { both: ["CLAIM"] }, launches: { solo: "skill-01", both: "skill-01", primary: "in-progress" } }), { kind: "state", id: "in_progress" });
  const moon = scene.planets.find((p) => p.name === "skill-01")!;

  it("orbits the one machine its only tie launches, as a small dot past the moon's name side", () => {
    const s = scene.stars.solo, out = Math.sign(moon.x - scene.hub!.x);

    expect([s.owned, moon.owned]).toEqual([moon, 1]);
    expect([s.br, s.y, (s.x - moon.x) * out > moon.rim!]).toEqual([5, moon.y, true]);
    expect(s.tether).toMatchObject({ x: moon.x, y: moon.y, crit: ["launches skill-01"] });
  });

  it("draws its one tether, to the machine it orbits, only while it is hovered", () => {
    expect(tethersDrawn(scene, null)).toEqual([]);
    expect(tethersDrawn(scene, scene.stars.solo).map(([s, t]) => [s.name, t])).toEqual([["solo", scene.stars.solo.tether]]);
  });

  it("leaves a DAG with another tie, or one that launches the primary, on the rings", () => {
    expect([scene.stars.both.owned, scene.stars.primary.owned]).toEqual([undefined, undefined]);
    expect(scene.stars.both.tether!.crit).toEqual(["writes CLAIM (ready → in_progress)", "launches skill-01"]);
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

  it("is what drilling the Board's fold on the Review → Done path opens, laid out from the snapshot's cues", () => {
    const sk = boardSky({ writes: { alpha: ["MERGED"] }, cues: [{ dag: "beta", event: "MERGED", state: "done", on: "push to main", resolves: "forced" }, { dag: "delta", event: "MERGED", state: "done", on: "push to main", resolves: "next" }] });
    const fold = Object.values(build(sk, { kind: "board" }).stars).find((s) => s.fold)!, edge = fold.tether!.edge!;
    const d = drill(fold, fold.tether!.crit, [edge.source, edge.target]);

    expect("push" in d && d.push).toMatchObject({ kind: "fold", path: ["review", "done"], dags: ["alpha", "beta", "delta"] });
    const scene = build(sk, "push" in d ? d.push : { kind: "board" }), l = scene.fold!.ledger!;
    expect([scene.fold!.a!.id, scene.fold!.b!.id, l.event, l.rows, l.cols.map((c) => [c.dag, c.role, c.resolves])]).toEqual(["review", "done", "MERGED", "merge", [["alpha", "writer", null], ["beta", "cue", "forced"], ["delta", "cue", "next"]]]);
  });

  describe("a merge Ledger's rows", () => {
    const row = (key: string, at: number, over: Partial<LedgerRow> = {}): LedgerRow => ({ key, at, tasks: [`TASK-${at}`], sha: key.repeat(7), runs: {}, fails: {}, pinned: false, ...over });
    const rows = [row("c", 300), row("b", 200, { appliedBy: "c" }), row("a", 100, { appliedBy: "gone" }), row("z", 50, { appliedBy: null })];
    const merged = (list: LedgerRow[] = rows, scale?: number) => {
      const sk = boardSky({ writes: { alpha: ["MERGED"] }, cues: cues.filter((c) => c.event === "MERGED"), ledgers: { MERGED: list } });
      return build({ ...sk, scale }, fold(["review", "done"], "MERGED"));
    };

    it("hang newest first under the cue bus, one cell in each template's column", () => {
      const scene = merged(), l = scene.fold!.ledger!, g = l.grid!;

      expect(g.rows.map((r) => r.row.key)).toEqual(["c", "b", "a", "z"]);
      expect(g.rows[0].y).toBeGreaterThan(l.bus);
      g.rows.forEach((r, i) => i && expect(r.y - g.rows[i - 1].y).toBeCloseTo(g.rh));
      expect(g.rows[0].cells.map((c) => c.dag)).toEqual(l.cols.map((c) => c.dag));
      g.rows[0].cells.forEach((c, i) => expect([c.gx > l.cols[i].x0, c.tx < l.cols[i].x1, c.room > 0]).toEqual([true, true, true]));
    });

    it("keep the left gutter wide enough for a row's time, task and title before the spine", () => {
      const g = merged().fold!.ledger!.grid!, bare = merged([]).fold!.ledger!;

      expect(g.label.w).toBeGreaterThan(150);
      expect(g.label.x + g.label.w).toBeLessThan(merged().fold!.ledger!.J.x);
      expect(bare.grid).toBeUndefined();
    });

    it("put another repository's merge on the cross lane, linked to the pin-bump row that applies it when that row is shown", () => {
      const g = merged().fold!.ledger!.grid!, by = Object.fromEntries(g.rows.map((r) => [r.row.key, r]));

      expect(g.rows.map((r) => r.cross)).toEqual([false, true, true, true]);
      expect(g.lane).toBeGreaterThan(merged().fold!.ledger!.J.x);
      expect([by.b.bump, by.a.bump, by.z.bump, by.c.bump]).toEqual(["c", null, null, null]);
    });

    it("shows only the rows that fit the level and grows the fit box to hold them", () => {
      const many = Array.from({ length: 80 }, (_, i) => row(`m${i}`, 1000 - i)), scene = merged(many), g = scene.fold!.ledger!.grid!;

      expect(g.rows.length).toBeLessThan(80);
      expect(g.rows.length).toBeGreaterThanOrEqual(1);
      expect(g.rows.at(-1)!.y + g.rh / 2).toBeLessThanOrEqual(scene.box![3]);
      expect(scene.box![3]).toBeLessThanOrEqual(scene.h);
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

  it("lays a Board out afresh when a state's room changes", () => {
    const before = geom(build(dagSky(), { kind: "board" })), busy = dagSky();
    busy.S.flows.board.agents = Array.from({ length: 40 }, (_, i) => ({ id: `T-${i}`, title: "t", state: "review", model: "", labels: [] })) as never;
    expect(geom(build(busy, { kind: "board" }))).not.toEqual(before);
  });
});

describe("a Board whose every open state opens into lifecycle machines", () => {
  const ALL = SAVED_STATES.filter((id) => id !== "completed" && id !== "archived");
  /** Every open state opens into `n` machines, the primary and the rest each holding a sub-state that opens a child machine, with tasks working them. */
  const everyState = (n: number, tasks = 4, W = 1920, H = 1080, OPEN = ALL, short = false, dags = false) => savedBoardSky(W, H, (snap) => {
    const board = snap.flows[0], flows: Snapshot["flows"] = [];
    // the live Board's DAGs: long names writing the paths beside crowded states, three folded on one path, and ten free in the hangar
    if (dags) {
      const writes: Record<string, string[]> = { waiting_ready: ["dagu/board-dependency-reconciliation"], ready_in_progress: ["dagu/board-autopilot"], done_completed: ["dagu/backlog-sweep"], review_done: ["dagu/main-follow", "dagu/apply-merged", "dagu/pr-reaper"] };
      const free = { Ops: ["a", "b", "c", "d", "e", "f"].map((x) => `dagu/ops-${x}`), Docs: ["a", "b", "c", "d"].map((x) => `dagu/docs-${x}`) }, tied = Object.values(writes).flat();
      board.machine.writers = Object.fromEntries(Object.entries(writes).map(([e, ns]) => [e, ns.map((actor) => ({ actor, trigger: "dagu" }))]));
      snap.dags = [...tied, ...Object.values(free).flat()].map((d) => dag(d, [["run", []]]));
      snap.domains = [{ name: "Board", dags: tied.map((name) => ({ name, runSafe: false })) }, ...Object.entries(free).map(([name, ds]) => ({ name, dags: ds.map((d) => ({ name: d, runSafe: false })) }))];
    }
    board.agents = OPEN.flatMap((state) => Array.from({ length: tasks }, (_, i) => ({ id: `${state}-${i}`, title: "t", state, model: "", labels: [] })));
    board.machine.subflows = OPEN.flatMap((state) => Array.from({ length: n }, (_, i) => {
      const name = short ? `${state.slice(0, 2)}${i}` : `${state}-machine-${String(i).padStart(2, "0")}`;
      flows.push({ name, agents: board.agents.filter((a) => a.state === state && i === 0).map((a, j) => ({ id: `${a.id}-s`, title: "t", state: "reading", model: "", task: a.id, active: 900 + j })), machine: machine(["reading", "writing"], short ? {} : { subflows: [{ state: "reading", flow: "child", exits: {}, parent: name, when: "it reads" }] }) });
      return { state, flow: name, exits: {}, parent: "board", when: "" };
    }));
    flows.push({ name: "child", agents: [], machine: machine(["a", "b"]) });
    snap.flows.push(...flows);
    snap.graphs.push(...flows.map((f) => f.name));
  });
  const boxes = (scene: Scene, W: number) => {
    const F = scene.unit ?? scene.w / (0.94 * W), at = (id: string) => ({ x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity, id });
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

  it.each([[12, 1920], [20, 1920], [12, 1420], [20, 1420]])("holds 40 px between one state's tasks, moons and moon names and the next state's, at %i machines a state on a %i px canvas", (n, W) => {
    const scene = build(everyState(n, 4, W, 1080, ALL), { kind: "board" }), bs = boxes(scene, W), short: string[] = [];
    for (const a of bs) for (const b of bs) if (a.id < b.id && Math.max(b.x0 - a.x1, a.x0 - b.x1, b.y0 - a.y1, a.y0 - b.y1) < 40 - 1e-6) short.push(`${a.id}/${b.id}`);

    expect(short).toEqual([]);
  });

  it.each([[12, 1920], [20, 1920], [12, 1420], [20, 1420]])("keeps every state, task, moon and moon name inside the fitted sky at %i machines a state on a %i px canvas", (n, W) => {
    const scene = build(everyState(n, 4, W, 1080, ALL), { kind: "board" }), bs = boxes(scene, W);

    expect(scene.w / scene.h).toBeCloseTo(W / 1080, 1);
    for (const b of bs) expect([b.id, b.x0 >= 0, b.x1 <= scene.w, b.y0 >= 0, b.y1 <= scene.h]).toEqual([b.id, true, true, true, true]);
  });

  /** Every state's disc, name and count line and moon rows, every DAG body with its name, and the DAGs hangar with its name, each as a box. */
  const labels = (scene: Scene, W: number) => {
    const F = scene.unit ?? scene.w / (0.94 * W), out: { o: string; x0: number; x1: number; y0: number; y1: number }[] = [];
    const add = (o: string, x: number, hw: number, y0: number, y1: number) => out.push({ o, x0: x - hw, x1: x + hw, y0, y1 });
    for (const g of Object.values(scene.galaxies)) {
      const sub = `${g.n}${g.subs.length ? ` · ${g.subs.length} lifecycles` : ""}`;
      add(g.id, g.lab.x, (Math.max(textW(g.name, 13), textW(sub, 11)) / 2) * F, g.lab.y - 6.5 * F, g.lab.y + 21.5 * F);
      add(g.id, g.x, g.R, g.y - g.R, g.y + g.R);
    }
    for (const m of scene.moons) {
      const sg = m.x < m.parent.x ? -1 : 1, end = m.x + sg * (m.R + m.ext + 10 + textW(scene.clipped ? clip(m.label) : m.label, 10.5) * F);
      out.push({ o: m.parent.id, x0: Math.min(m.x - m.R, end), x1: Math.max(m.x + m.R, end), y0: m.y - Math.max(m.R, 5.25 * F), y1: m.y + Math.max(m.R, 5.25 * F) });
    }
    for (const s of Object.values(scene.stars)) add(s.name, s.x, Math.max(s.glyph.w / 2, (textW(s.label, 11) * F) / 2), s.y - s.glyph.h / 2, s.y + s.glyph.h / 2 + 21.5 * F);
    const h = scene.hangar!;
    add("hangar", h.x, Math.max(h.r, (textW("DAGs", 12.5) * F) / 2, (textW(`${h.names.length} · ${h.doms} domains`, 10.5) * F) / 2), h.y - h.r, h.y + h.r + 30 + 27 * F);
    return out;
  };

  it.each([[12, 1920], [20, 1920], [12, 1420], [20, 1420]])("keeps state names, DAG names and the DAGs hangar off each other and off every other state's rows at %i machines a state on a %i px canvas", (n, W) => {
    const scene = build(everyState(n, 4, W, 1080, ALL, false, true), { kind: "board" }), bs = labels(scene, W), hit: string[] = [];
    bs.forEach((a, i) => bs.slice(i + 1).forEach((b) => { if (a.o !== b.o && a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1) hit.push(`${a.o}/${b.o}`); }));

    expect([Object.keys(scene.stars).length, scene.hangar?.names.length, hit]).toEqual([4, 10, []]);
  });

  const shownOf = (scene: Scene) => ALL.map((id) => scene.moons.filter((m) => m.parent.id === id && !m.pager).length - 1);

  it.each([[1920], [1420]])("pages no state below MIN_PAGE machines, however wide the Board, on a %i px canvas", (W) => {
    const scene = build(everyState(12, 4, W, 1080, ALL), { kind: "board" });

    expect(Math.min(...shownOf(scene))).toBeGreaterThanOrEqual(MIN_PAGE);
  });

  it("cuts moon names to NAME_MAX only once pages of MIN_PAGE still leave the sky past BOARD_GROW times its base", () => {
    const scene = build(everyState(12, 4, 1420, 1080, ALL), { kind: "board" });

    expect([scene.clipped, new Set(shownOf(scene))]).toEqual([true, new Set([MIN_PAGE])]);
  });

  it("zooms out past BOARD_GROW times its base: the names and rows keep the size they had there while the sky grows", () => {
    const wide = build(everyState(12, 4, 1420, 1080, ALL), { kind: "board" }), fits = build(everyState(12, 4, 1920, 1080, ["in_progress"]), { kind: "board" });

    expect([wide.unit, wide.w > BOARD_GROW * 1860, fits.unit]).toEqual([(BOARD_GROW * 1860) / (0.94 * 1420), true, undefined]);
  });

  it("keeps moon names whole on a Board that fits", () => {
    const scene = build(everyState(12, 4, 1920, 1080, ["in_progress"]), { kind: "board" });

    expect([scene.clipped ?? false, scene.moons.filter((m) => m.pager)]).toEqual([false, []]);
  });


  it("pages each state to its own size, keeping names whole, when pages of MIN_PAGE or more fit the sky", () => {
    const scene = build(everyState(12, 4, 1420, 1080, ALL, true), { kind: "board" }), shown = shownOf(scene);

    expect([scene.clipped, scene.w <= BOARD_GROW * 1860, Math.min(...shown) >= MIN_PAGE, Math.max(...shown) > Math.min(...shown)]).toEqual([false, true, true, true]);
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

  it("keeps the fixed minimum while its tasks fit one ring", () => {
    expect(build(withTasks({ ready: 1 }), { kind: "board" }).galaxies.ready.r).toBe(39);
  });

  it.each([60, 80])("grows on the Board so %i tasks circle it in one ring", (n) => {
    const g = build(withTasks({ ready: n }), { kind: "board" }).galaxies.ready;

    expect(g.rings).toHaveLength(1);
  });

  it.each([140, 300])("stops at the fixed maximum on the Board and circles %i tasks in more rings", (n) => {
    const g = build(withTasks({ ready: n }), { kind: "board" }).galaxies.ready;

    expect([g.r, g.rings!.length > 1]).toEqual([140, true]);
  });

  it("grows on a state level with no machines so every task circles it in one ring, up to the fixed maximum", () => {
    const sun = build(withTasks({ ready: 40 }), { kind: "state", id: "ready" }).sun!, full = build(withTasks({ ready: 200 }), { kind: "state", id: "ready" }).sun!;

    expect([sun.r > 34, sun.rings?.length, full.r]).toEqual([true, 1, 140]);
  });

  it("grows the primary on a state level with machines so every task circles it in one ring", () => {
    const hub = build(withTasks({ in_progress: 200 }), { kind: "state", id: "in_progress" }).hub!;

    expect([hub.R > 104, hub.rings?.length]).toEqual([true, 1]);
  });
});

describe("a task's trail on a state level", () => {
  it("lists each body the task moved to in the events, in order, naming the primary's state while it is on the primary", () => {
    const scene = build(inProgressSky(), { kind: "state", id: "in_progress" });

    expect(scene.hostTrail!("PROJ-1")).toEqual([{ at: 800, host: "in-progress#worktree_ready" }, { at: 900, host: "triaging-cr-reviews" }, { at: 980, host: "in-progress#worktree_ready" }]);
  });
});

describe("a DAG's label", () => {
  it("drops the namespace when no other DAG shares the bare name", () => {
    const scene = build(boardSky({ writes: { "dagu/board-autopilot": ["CLAIM"], "dagu/nightly": ["MERGED"], "kit/nightly": ["REVIEW"] } }), { kind: "board" });

    expect(scene.stars["dagu/board-autopilot"].label).toBe("board-autopilot");
    expect([scene.stars["dagu/nightly"].label, scene.stars["kit/nightly"].label]).toEqual(["dagu/nightly", "kit/nightly"]);
  });
});

describe("a Board state's sun sized from its share of the week's moves", () => {
  const sized = (suns: Record<string, number>, counts: Record<string, number> = {}) => {
    const sky = withTasks(boardSky(), counts);
    sky.S.suns = suns;
    return build(sky, { kind: "board" }).galaxies;
  };
  const shares = { new: 0.1, ready: 0.1, in_progress: 0.2, review: 0.2, done: 0.4 };

  it("has an area proportional to its share, the busiest state's reaching the maximum", () => {
    const g = sized(shares);

    expect(g.done.r).toBe(GALAXY_MAX);
    expect((g.review.r / g.done.r) ** 2).toBeCloseTo(0.5);
    expect((g.ready.r / g.done.r) ** 2).toBeCloseTo(0.25);
  });
  it("never falls below the minimum, however quiet the state, so it stays visible", () => {
    const g = sized({ ...shares, new: 0.001, ready: 0 });

    expect([g.new.r, g.ready.r]).toEqual([GALAXY_MIN, GALAXY_MIN]);
  });
  it("is the minimum on every state when the week held no move", () => {
    const g = sized({ new: 0, ready: 0, in_progress: 0, review: 0, done: 0 });

    expect([g.new.r, g.ready.r, g.review.r, g.done.r]).toEqual([GALAXY_MIN, GALAXY_MIN, GALAXY_MIN, GALAXY_MIN]);
  });
  it("does not follow the state's live tasks, so activity never resizes it", () => {
    const quiet = sized(shares), busy = sized(shares, { new: 5, ready: 80, review: 120, done: 3000 });

    for (const id of Object.keys(quiet)) expect(busy[id].r).toBe(quiet[id].r);
  });
  it("sizes the state's own level's sun the same as the Board's state", () => {
    const sky = boardSky();
    sky.S.suns = shares;

    expect(build(sky, { kind: "state", id: "done" }).sun!.r).toBe(GALAXY_MAX);
    expect(build(sky, { kind: "state", id: "review" }).sun!.r).toBe(build(sky, { kind: "board" }).galaxies.review.r);
  });
});

describe("a flow shared by two Board states", () => {
  // `ci` opens under In Progress and under Review; each machine task names the Board task it works.
  const shared = () => {
    const snap: Snapshot = {
      graphs: ["board", "ci", "runs"],
      flows: [
        { name: "board", machine: machine(["ready", "in_progress", "review"], { subflows: [
          { state: "in_progress", flow: "ci", exits: {}, parent: "board", when: "a PR is open" },
          { state: "review", flow: "ci", exits: {}, parent: "board", when: "a PR is open" },
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
