import { describe, expect, it } from "vitest";
import { BOARD, drill, hostOf, pathKey, pathTo, startPath, taskKicker, topOf, tree, type Level, type Path } from "./levels";
import type { Machine, Snapshot } from "./types";

const machine = (ids: string[], subflows: Machine["subflows"] = [], source?: string): Machine => ({
  ...(source ? { source } : {}),
  states: ids.map((id, i) => ({ id, name: id.replace(/_/g, " "), initial: i === 0, final: false })),
  transitions: [],
  subflows,
});
// The live shape: the Board opens In Progress into the delivery machine, which opens pr_opened into CR triage.
const SNAP: Snapshot = {
  graphs: ["board", "in-progress", "triaging-cr-reviews", "auditing-docs", "graph-traversal", "runs"],
  flows: [
    { name: "board", agents: [], machine: machine(["ready", "in_progress", "review"], [
      { state: "in_progress", flow: "in-progress", exits: {}, parent: "board", when: "" },
    ]) },
    { name: "in-progress", agents: [], machine: machine(["worktree_ready", "pr_opened"], [
      { state: "pr_opened", flow: "triaging-cr-reviews", exits: {}, parent: "in-progress", when: "a PR is open" },
    ]) },
    { name: "triaging-cr-reviews", agents: [], machine: machine(["fetch", "done"]) },
  ],
  dags: [], settled: {}, error: null, now: 0,
};
const T = tree(SNAP);
const IN_PROGRESS: Path = [...BOARD, { kind: "state", id: "in_progress" }];
const DELIVERY: Path = [...IN_PROGRESS, { kind: "machine", flow: "in-progress" }];

describe("the level tree", () => {
  it("opens the Board's sub-flow and every skill machine under the sub-flow's state, and a child under its parent", () => {
    expect(T.subs).toEqual({ in_progress: ["in-progress", "auditing-docs", "graph-traversal"] });
    expect(T.children).toEqual({ "in-progress": [{ state: "pr_opened", flow: "triaging-cr-reviews", when: "a PR is open" }] });
  });

  it("finds the path down to any machine", () => {
    expect(pathTo(T, "in-progress")).toEqual(DELIVERY);
    expect(pathTo(T, "auditing-docs")).toEqual([...IN_PROGRESS, { kind: "machine", flow: "auditing-docs" }]);
    expect(pathTo(T, "triaging-cr-reviews")).toEqual([...DELIVERY, { kind: "machine", flow: "triaging-cr-reviews" }]);
  });
});

describe("a mapped machine", () => {
  const mapped: Snapshot = {
    ...SNAP,
    graphs: [...SNAP.graphs, "ci"],
    flows: [...SNAP.flows, { name: "ci", agents: [], machine: machine(["opened", "running"], [], "GitHub") }],
  };

  it("is found in the level tree by flow name, and only a machine that names a source is", () => {
    expect(tree(mapped).sources).toEqual({ ci: "GitHub" });
    expect(tree(SNAP).sources).toEqual({});
  });

  it("puts its source in a task's kicker, and a local machine's kicker names none", () => {
    expect(taskKicker("ci", "running", tree(mapped).sources!.ci)).toBe("task · ci · mapped from GitHub · running");
    expect(taskKicker("in-progress", "pr_opened")).toBe("task · in-progress · pr_opened");
  });
});

describe("old URLs", () => {
  it("map each retired page to the level that draws it", () => {
    expect(startPath("/board", "", null, T)).toEqual(BOARD);
    expect(startPath("/runs", "", null, T)).toEqual(BOARD);
    expect(startPath("/flow/in-progress", "", null, T)).toEqual(DELIVERY);
    expect(startPath("/flow/triaging-cr-reviews", "", null, T)).toEqual(pathTo(T, "triaging-cr-reviews"));
    expect(startPath("/", "#sec-auditing-docs", null, T)).toEqual(pathTo(T, "auditing-docs"));
  });

  it("reopen the cached path at the root, and the Board when there is none or it names a machine that is gone", () => {
    expect(startPath("/", "", DELIVERY, T)).toEqual(DELIVERY);
    expect(startPath("/", "", null, T)).toEqual(BOARD);
    expect(startPath("/", "", [...IN_PROGRESS, { kind: "machine", flow: "retired-skill" }], T)).toEqual(BOARD);
    expect(startPath("/flow/retired-skill", "", DELIVERY, T)).toEqual(BOARD);
  });

  it("reopen the DAGs level one step below the Board, and no deeper", () => {
    const dags: Path = [...BOARD, { kind: "dags" }];

    expect(startPath("/", "", dags, T)).toEqual(dags);
    expect(startPath("/", "", [...dags, { kind: "state", id: "review" }], T)).toEqual(BOARD);
  });

  it("reopen a fold one step below the Board while its states still exist, and never from the DAGs level", () => {
    const fold: Level = { kind: "fold", dags: ["a", "b"], crit: ["a: writes X (ready → review)"], path: ["ready", "review"] };
    const gone: Level = { ...fold, path: ["ready", "retired"] };

    expect(startPath("/", "", [...BOARD, fold], T)).toEqual([...BOARD, fold]);
    expect(startPath("/", "", [...BOARD, gone], T)).toEqual(BOARD);
    expect(startPath("/", "", [...BOARD, { kind: "dags" }, fold], T)).toEqual(BOARD);
    expect(startPath("/", "", [...BOARD, { ...fold, path: null }], T)).toEqual([...BOARD, { ...fold, path: null }]);
  });

  it("key a fold by the DAGs it holds", () => {
    expect(pathKey([...BOARD, { kind: "fold", dags: ["a", "b"], crit: [], path: null }])).toBe("board/a+b");
  });
});

describe("drill", () => {
  const crit = ["a: writes X (ready → review)", "b: runs on Y, beside X (ready → review)"];

  it("opens a single DAG's panel and leaves the level alone", () => {
    expect(drill({ name: "a" }, crit, ["ready", "review"])).toEqual({ panel: "a" });
  });

  it("pushes a fold level over the path a fold's DAGs write", () => {
    expect(drill({ name: "2 DAGs", fold: ["a", "b"] }, crit, ["ready", "review"])).toEqual({
      push: { kind: "fold", dags: ["a", "b"], crit, path: ["ready", "review"] },
    });
  });
});

describe("one flow under several Board states", () => {
  // The live shape of the mapped CI machine: In Progress and Review each open the same `ci` flow.
  const shared: Snapshot = {
    graphs: ["board", "in-progress", "ci", "runs"],
    flows: [
      { name: "board", agents: [], machine: machine(["ready", "in_progress", "review"], [
        { state: "in_progress", flow: "in-progress", exits: {}, parent: "board", when: "" },
        { state: "in_progress", flow: "ci", exits: {}, parent: "board", when: "a PR is open" },
        { state: "review", flow: "ci", exits: {}, parent: "board", when: "a PR is open" },
      ]) },
      { name: "in-progress", agents: [], machine: machine(["worktree_ready"]) },
      { name: "ci", agents: [], machine: machine(["opened", "running"]) },
    ],
    dags: [], settled: {}, error: null, now: 0,
  };
  const S = tree(shared);
  const under = (state: string): Path => [...BOARD, { kind: "state", id: state }, { kind: "machine", flow: "ci" }];

  it("lists the flow under each host", () => {
    expect(S.subs).toEqual({ in_progress: ["in-progress", "ci"], review: ["ci"] });
  });

  it("resolves the (state, flow) pair to its own level, and a bare flow to its first host", () => {
    expect(pathTo(S, "ci", "review")).toEqual(under("review"));
    expect(pathTo(S, "ci", "in_progress")).toEqual(under("in_progress"));
    expect(pathTo(S, "ci")).toEqual(under("in_progress"));
    expect(pathTo(S, "ci", "ready")).toBeNull();
    expect(pathKey(under("review"))).toBe("board/review/ci");
  });

  it("names the Board state a level sits under", () => {
    expect(hostOf(under("review"))).toBe("review");
    expect(hostOf(BOARD)).toBeUndefined();
  });

  it("reopens a cached path under either host, and the Board when the flow is not under that state", () => {
    expect(startPath("/", "", under("review"), S)).toEqual(under("review"));
    expect(startPath("/", "", under("in_progress"), S)).toEqual(under("in_progress"));
    expect(startPath("/", "", under("ready"), S)).toEqual(BOARD);
  });
});

describe("the machine drawn across a level's top", () => {
  it("is what drilling the Board state that opens the primary machine shows, named by that machine", () => {
    expect(topOf(T.subs, { kind: "state", id: "in_progress" })).toBe("in-progress");
  });

  it("is no other Board state, and no machine level under it", () => {
    expect(topOf(T.subs, { kind: "state", id: "review" })).toBeNull();
    expect(topOf(T.subs, { kind: "machine", flow: "in-progress" })).toBeNull();
    expect(topOf(T.subs, { kind: "board" })).toBeNull();
  });
});
