import { describe, expect, it } from "vitest";
import { boardTies, nameLines, nameOf, obstacles, over, type Hub } from "./dagTies";
import { build, type Scene } from "./scene";
import { fitLevel } from "./zoom";
import { merge, Moves } from "./sky";
import type { Cue, Dag, Machine, Snapshot } from "./api";

// The live Board of 2026-10-07 (doc-111, D7b): ten states, the writers and cues of its tied DAGs, and DAGs that only launch or have no tie.
const STATES = ["new", "ready", "blocked", "waiting", "in_progress", "review", "needs_attention", "done", "completed", "archived"];
const TRANSITIONS: [string, string, string][] = [
  ["new", "in_progress", "CREATE_IN_PROGRESS"], ["ready", "in_progress", "CLAIM"], ["ready", "waiting", "WAIT_ON_DEPS"], ["in_progress", "waiting", "DEFER"],
  ["waiting", "ready", "DEP_RESOLVED"], ["blocked", "ready", "DEPS_DONE"], ["in_progress", "review", "CRITERIA_MET"], ["review", "in_progress", "CRITERIA_UNMET"],
  ["review", "done", "MERGED"], ["done", "completed", "SWEEP"], ["needs_attention", "ready", "RETRY"], ["ready", "archived", "ARCHIVE"],
];
const WRITES: Record<string, string[]> = {
  "dagu/board-autopilot": ["CREATE_IN_PROGRESS", "CLAIM", "WAIT_ON_DEPS", "DEFER"],
  "dagu/board-dependency-reconciliation": ["DEP_RESOLVED", "DEPS_DONE", "CRITERIA_MET", "CRITERIA_UNMET"],
  "dagu/main-follow": ["MERGED"],
  "dagu/backlog-sweep": ["SWEEP"],
};
const CUES: Cue[] = [
  { dag: "dagu/apply-on-merge", event: "MERGED", on: "each merge", resolves: "forced", state: "done" },
  { dag: "dagu/graph-refresh", event: "MERGED", on: "each merge", resolves: "next", state: "done" },
];
const LAUNCH_ONLY = ["dagu/nightly-audit", "dagu/weekly-code-audit"], UNTIED = ["dagu/orphan-report"];

const dag = (name: string, status: Dag["status"] = "succeeded"): Dag => ({ name, status, runId: "r", startedAt: "", finishedAt: "", steps: [] });
const machine: Machine = {
  states: STATES.map((id, i) => ({ id, name: id, initial: i === 0, final: id === "completed" || id === "archived" })),
  transitions: TRANSITIONS.map(([source, target, event]) => ({ source, target, event })),
  mainLine: ["new", "ready", "in_progress", "review", "done"],
  writers: Object.fromEntries(Object.entries(WRITES).flatMap(([d, evs]) => evs.map((e) => [e, [{ actor: d, trigger: "dagu" }]] as const))),
  launches: Object.fromEntries(["dagu/board-autopilot", ...LAUNCH_ONLY].map((d) => [d, { skill: "delivering", flow: null }])),
  dagActors: Object.keys(WRITES),
};
const liveSky = (status: Record<string, Dag["status"]> = {}) => {
  const names = [...Object.keys(WRITES), ...CUES.map((c) => c.dag), ...LAUNCH_ONLY, ...UNTIED];
  const snap: Snapshot = {
    graphs: ["board"],
    flows: [{ name: "board", agents: [], machine }],
    dags: names.map((n) => dag(n, status[n])),
    domains: [], cues: CUES, settled: {}, error: null, now: 1000,
  };
  const S = merge(snap), moves = new Moves();
  moves.observe(S, 1000);
  return { S, moves, W: 1920, H: 1080, T: 1000 };
};
/** World units a screen pixel at the Board's fit, as the renderer reads it. */
const unitOf = (sc: Scene) => 1 / Math.max(fitLevel(sc, 1920, 1080).k, sc.unit ? 1 / sc.unit : 0);

describe("the tied DAGs of the Board level", () => {
  const ctx = liveSky(), sc = build(ctx, { kind: "board" }), ties = boardTies(sc, ctx.S, unitOf(sc));
  const hubOf = (state: string) => ties.hubs.find((h) => h.state === state);

  it("puts each DAG in the hangar of the state most of its ties act on", () => {
    // board-autopilot writes from new (1), ready (2) and in_progress (1); reconciliation's four ties each act on another state, so the first wins
    expect(hubOf("ready")?.orbs.map((o) => o.dag)).toEqual(["dagu/board-autopilot"]);
    expect(hubOf("waiting")?.orbs.map((o) => o.dag)).toEqual(["dagu/board-dependency-reconciliation"]);
    expect(hubOf("review")?.orbs.map((o) => o.dag)).toEqual(["dagu/main-follow"]);
    // a cue belongs to the state its event lands in, beside the DAG that writes that state's transition
    expect(hubOf("done")?.orbs.map((o) => o.dag).sort()).toEqual(["dagu/apply-on-merge", "dagu/backlog-sweep", "dagu/graph-refresh"]);
    expect(ties.hubs).toHaveLength(4);
  });

  it("leaves launch-only and untied DAGs out", () => {
    const drawn = ties.hubs.flatMap((h) => h.orbs.map((o) => o.dag));
    for (const d of [...LAUNCH_ONLY, ...UNTIED]) expect(drawn).not.toContain(d);
    expect(new Set(drawn).size).toBe(drawn.length);
  });

  it("docks each orbiter by a transition of its state, on its ring", () => {
    for (const h of ties.hubs)
      for (const o of h.orbs) {
        expect(o.primary?.state).toBe(h.state);
        expect(Math.hypot(o.x - h.c.x, o.y - h.c.y)).toBeCloseTo(h.orbit, 6);
      }
  });
});

describe("the hangar names, placed round the ring", () => {
  const ctx = liveSky(), sc = build(ctx, { kind: "board" }), u = unitOf(sc);

  for (const ts of [1, 1.25, 1.5]) {
    const ties = boardTies(sc, ctx.S, u, ts);

    it(`keep every name box clear of state names, moon labels and other orbiters at ${ts * 100}% text`, () => {
      expect(ties.hubs.length).toBeGreaterThan(0);
      for (const h of ties.hubs) {
        const others = ties.hubs.filter((x) => x !== h);
        // every state's disc and name, every moon and its label, and the other hangars' name boxes and orbiters:
        const keep = obstacles(sc, others, u, ts);
        for (const k of keep) expect(over([...h.box, 1], k), `${h.state} at ${ts}`).toBe(0);
      }
    });

    it(`break the ring arc where it would cross the name at ${ts * 100}% text`, () => {
      for (const h of ties.hubs) {
        expect(h.arcs.length).toBeGreaterThan(0);
        for (const [a0, a1] of h.arcs)
          for (let a = a0; a <= a1; a += 0.01) {
            const x = h.c.x + Math.cos(a) * h.orbit, y = h.c.y + Math.sin(a) * h.orbit;
            expect(x > h.box[0] && x < h.box[2] && y > h.box[1] && y < h.box[3], `${h.state} arc at ${a}`).toBe(false);
          }
      }
    });
  }
});

describe("a hangar's name", () => {
  const orbs = (...labels: string[]) => labels.map((label) => ({ label })) as Hub["orbs"];

  it("is its one DAG's name, or how many DAGs it holds", () => {
    expect(nameOf(orbs("main-follow"))).toBe("main-follow");
    expect(nameOf(orbs("a", "b", "c"))).toBe("3 DAGs");
  });

  it("breaks a lone long name after the hyphen nearest the middle", () => {
    expect(nameLines(orbs("board-autopilot"))).toEqual(["board-", "autopilot"]);
    expect(nameLines(orbs("board-dependency-reconciliation"))).toEqual(["board-dependency-", "reconciliation"]);
  });

  it("keeps a name of 12 characters or fewer, a name with no hyphen and a count whole", () => {
    expect(nameLines(orbs("main-follow"))).toEqual(["main-follow"]);
    expect(nameLines(orbs("graphrefreshing"))).toEqual(["graphrefreshing"]);
    expect(nameLines(orbs("board-autopilot", "main-follow"))).toEqual(["2 DAGs"]);
  });
});
