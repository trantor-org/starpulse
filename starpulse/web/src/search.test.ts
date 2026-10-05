import { describe, expect, it } from "vitest";
import type { Tree } from "./levels";
import { search, spotIn, type SpotScene } from "./search";

const tree: Tree = { states: ["ready", "in_progress", "review"], subs: { in_progress: ["delivery", "review-loop"] }, children: { delivery: [{ state: "ci", flow: "ci-watch", when: "on push" }] } };
const sources = {
  tree,
  states: [{ id: "ready", name: "Ready", count: 3 }, { id: "in_progress", name: "In progress", count: 2 }, { id: "review", name: "Review", count: 1 }],
  counts: { delivery: 2, "ci-watch": 1 },
  dags: ["board-autopilot", "review-sweep"],
  cards: [
    { id: "TASK-D12", title: "Review the deploy script", lane: "in_progress" },
    { id: "TASK-D7", title: "Ready the hangar", lane: "ready" },
  ],
};

describe("the navigator search", () => {
  it("matches states, machines, DAGs and tasks in that order", () => {
    const hits = search("review", sources);
    expect(hits.map((h) => `${h.target.kind}:${h.label}`)).toEqual(["state:Review", "machine:review-loop", "dag:review-sweep", "task:TASK-D12"]);
  });

  it("finds a task by id or title, ignoring case, and opens a machine at its full path", () => {
    expect(search("task-d12", sources).map((h) => h.label)).toEqual(["TASK-D12"]);
    expect(search("DEPLOY", sources)[0]).toMatchObject({ label: "TASK-D12", sub: "Review the deploy script", target: { kind: "task", id: "TASK-D12", lane: "in_progress" } });
    const ci = search("ci-watch", sources)[0].target;
    expect(ci.kind === "machine" && ci.path.map((l) => ("flow" in l ? l.flow : "id" in l ? l.id : l.kind))).toEqual(["board", "in_progress", "delivery", "ci-watch"]);
  });

  it("returns nothing for a blank query", () => {
    expect(search("  ", sources)).toEqual([]);
  });
});

describe("what a search result spotlights on the canvas", () => {
  const galaxy = { id: "ready" }, moon = { name: "delivery" }, body = { id: "TASK-D7", gone: false }, star = { name: "2 DAGs", fold: ["review-sweep", "x"] }, hangar = { names: ["board-autopilot"] };
  const board: SpotScene = { galaxies: { ready: galaxy }, sun: null, moons: [moon], planets: [], stars: { "2 DAGs": star }, hangar, tasks: [body], machineTasks: [] };

  it("finds each kind of model the Board draws", () => {
    expect(spotIn(board, { kind: "state", id: "ready" })).toEqual({ kind: "galaxy", o: galaxy });
    expect(spotIn(board, { kind: "machine", flow: "delivery", path: [] })).toEqual({ kind: "moon", o: moon });
    expect(spotIn(board, { kind: "task", id: "TASK-D7", lane: "ready" })).toEqual({ kind: "task", o: body });
    // a DAG folded with others lights its fold; one free of the Board lights the hangar that holds it
    expect(spotIn(board, { kind: "dag", name: "review-sweep" })).toEqual({ kind: "dag", o: star });
    expect(spotIn(board, { kind: "dag", name: "board-autopilot" })).toEqual({ kind: "hangar", o: hangar });
  });

  it("lights the Board state a machine opens under when the Board draws no moon for it, as on another page", () => {
    const paged = { kind: "machine" as const, flow: "review-loop", path: [{ kind: "board" as const }, { kind: "state" as const, id: "ready" }, { kind: "machine" as const, flow: "review-loop" }] };
    expect(spotIn(board, paged)).toEqual({ kind: "galaxy", o: galaxy });
  });

  it("finds a state level's sun and planets, a machine's tasks, and nothing for a model the level does not draw", () => {
    const sun = { id: "in_progress" }, planet = { name: "review-loop" }, mtask = { id: "TASK-D12", _x: 1 };
    const level: SpotScene = { galaxies: {}, sun, moons: [], planets: [planet], stars: {}, hangar: null, tasks: [], machineTasks: [mtask] };
    expect(spotIn(level, { kind: "state", id: "in_progress" })).toEqual({ kind: "sun", o: sun });
    expect(spotIn(level, { kind: "machine", flow: "review-loop", path: [] })).toEqual({ kind: "planet", o: planet });
    expect(spotIn(level, { kind: "task", id: "TASK-D12", lane: "in_progress" })).toEqual({ kind: "mtask", o: mtask });
    expect(spotIn(level, { kind: "state", id: "ready" })).toBeNull();
    expect(spotIn(level, { kind: "dag", name: "nope" })).toBeNull();
  });
});
