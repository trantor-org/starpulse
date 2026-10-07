import { describe, expect, it } from "vitest";
import { age, firstOpened, rankRows, rowMeta, stuckCount } from "./machineRows";
import type { FlowSnapshot, Stuck, Tie } from "./api";

const NOW = 1_800_000_000;
const tie = (kind: Tie["kind"], machine: string | null, state: string | null, count: number | null, dag: string | null = null, when = ""): Tie => ({ kind, machine, state, count, dag, when });
/** A lifecycle machine with the fields the server derives for it (TASK-3116). */
function flow(name: string, o: { parent?: string | null; last?: number | null; stuck?: Stuck | null; ties?: Tie[]; nested?: string[]; states?: string[] } = {}): FlowSnapshot {
  const ids = o.states ?? ["a", "b", "c"];
  return {
    name,
    machine: { states: ids.map((id, i) => ({ id, name: id.replace(/^./, (c) => c.toUpperCase()).replace(/_/g, " "), initial: !i, final: i === ids.length - 1 })), transitions: ids.slice(1).map((t, i) => ({ source: ids[i], target: t, event: t })) },
    agents: [],
    ties: o.ties ?? [],
    parent: o.parent === undefined ? "in-progress" : o.parent,
    depth: 1,
    chain: [],
    nested: o.nested ?? [],
    last: o.last === undefined ? NOW : o.last,
    stuck: o.stuck ?? null,
  };
}
const stuck = (machine: string, state: string, since: number): Stuck => ({ machine, state, since });
const world = (...fs: FlowSnapshot[]) => Object.fromEntries([flow("in-progress", { parent: null }), flow("board", { parent: null }), ...fs].map((f) => [f.name, f]));

describe("the machine ledger's rows", () => {
  it("are the machines entered from the top machine, newest activity first, a stuck one keeping its place in that one sequence", () => {
    const flows = world(
      flow("old", { last: NOW - 5000 }),
      flow("stuck-new", { last: NOW - 60, stuck: stuck("stuck-new", "b", NOW - 3 * 3600) }),
      flow("newest", { last: NOW }),
      flow("stuck-old", { last: NOW - 9000, stuck: stuck("stuck-old", "b", NOW - 9000) }),
      flow("nested-below", { parent: "old" }),
      flow("quiet", { last: null }),
    );
    expect(rankRows(flows, "in-progress")).toEqual(["newest", "stuck-new", "old", "stuck-old", "quiet"]);
  });

  it("takes a drilled-in machine's own entered machines as its rows", () => {
    const flows = world(flow("old", { last: NOW - 5000 }), flow("kid-a", { parent: "old", last: NOW - 30 }), flow("kid-b", { parent: "old", last: NOW - 90 }));
    expect(rankRows(flows, "old")).toEqual(["kid-a", "kid-b"]);
    expect(rankRows(flows, "kid-a")).toEqual([]);
  });

  it("holds the order it was given while held, whatever has moved since, and lists a machine that appeared after it last", () => {
    const flows = world(flow("a", { last: NOW - 300 }), flow("b", { last: NOW - 200 }), flow("c", { last: NOW - 100 }));
    const held = rankRows(flows, "in-progress");
    expect(held).toEqual(["c", "b", "a"]);
    const later = world(flow("a", { last: NOW }), flow("b", { last: NOW - 200 }), flow("c", { last: NOW - 100 }), flow("d", { last: NOW + 10 }));
    expect(rankRows(later, "in-progress", held)).toEqual(["c", "b", "a", "d"]);
    expect(rankRows(later, "in-progress")).toEqual(["d", "a", "c", "b"]);
  });
});

describe("a row's meta column", () => {
  const states = ["start", "worktree_ready", "pr_opened"];
  const flows = world(
    flow("authoring-skills", { ties: [tie("declared", "in-progress", "worktree_ready", null, null, "a skill changes")], nested: ["running-skill-evals"], states: ["drafted", "tested"] }),
    flow("running-skill-evals", { parent: "authoring-skills", ties: [tie("observed", "authoring-skills", "tested", 4)], last: NOW - 120 }),
    flow("triaging-cr-reviews", { ties: [tie("observed", "in-progress", "pr_opened", 7), tie("observed", "in-progress", "start", 2)] }),
    flow("graph-refresh", { ties: [tie("dag", null, null, null, "graph-refresh"), tie("dag", null, null, null, "apply-on-merge")] }),
    flow("lonely", {}),
  );
  flows["in-progress"] = flow("in-progress", { parent: null, states });
  flows["authoring-skills"].agents = [{ id: "a", state: "tested" } as never, { id: "b", state: "tested" } as never];
  const meta = (n: string, top = "in-progress") => rowMeta(flows, n, top, NOW);

  it("names a declared tie, its state and that it is declared", () => {
    expect(meta("authoring-skills").tie).toEqual({ text: "from Worktree ready · declared", machine: "in-progress", state: "worktree_ready", kind: "declared" });
  });
  it("names an observed tie with its count, from the leading tie only", () => {
    expect(meta("triaging-cr-reviews").tie).toEqual({ text: "from Pr opened · ×7", machine: "in-progress", state: "pr_opened", kind: "observed" });
  });
  it("names the row it is entered from when that is not the top machine", () => {
    expect(meta("running-skill-evals", "in-progress").tie.text).toBe("on authoring-skills › Tested · ×4");
    expect(meta("running-skill-evals", "authoring-skills").tie.text).toBe("from Tested · ×4");
  });
  it("names a DAG launch with a star and every DAG, and no state", () => {
    expect(meta("graph-refresh").tie).toEqual({ text: "✦ graph-refresh, apply-on-merge", machine: null, state: null, kind: "dag" });
  });
  it("says so when nothing ties a machine in", () => {
    expect(meta("lonely").tie).toMatchObject({ text: "no tie this hour", kind: "none" });
  });
  it("ends the name line with a bare chevron, the band under the row showing its nesting", () => {
    expect(meta("authoring-skills").end).toBe("›");
    expect(meta("lonely").end).toBe("›");
  });
  it("counts states and tasks", () => {
    expect(meta("authoring-skills").sub).toBe("2 states · 2 tasks");
    expect(meta("lonely").sub).toBe("3 states · 0 tasks");
  });
});

describe("a row's status line", () => {
  const agents = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `t${i}`, state: "a" }) as never);
  const flows = world(
    flow("own", { last: NOW - 4 * 3600, stuck: stuck("own", "b", NOW - (4 * 3600 + 3 * 60)), states: ["a", "b", "c"] }),
    flow("above", { nested: ["deep"], last: NOW - 60, stuck: stuck("deep", "b", NOW - 2 * 3600 - 10 * 60) }),
    flow("deep", { parent: "above" }),
    flow("live", { last: NOW - 120 }),
    flow("idle", { last: NOW - (3 * 3600 + 5 * 60) }),
    flow("empty", { last: null }),
    flow("only-nested", { nested: ["live"], last: NOW - 120 }),
  );
  flows.own.agents = agents(2);
  flows.live.agents = agents(1);
  flows.idle.agents = agents(3);
  flows["only-nested"].agents = [];
  const status = (n: string) => rowMeta(flows, n, "in-progress", NOW).status;

  it("names the time and the state a task here has been stuck in, and marks the row", () => {
    expect(status("own")).toEqual({ text: "stuck 4h03 in B", stuck: true, idle: true });
  });
  it("names the machine below where the stuck task is, and marks the row", () => {
    expect(status("above")).toEqual({ text: "nested stuck 2h10 in deep", stuck: true, idle: false });
  });
  it("says what its tasks did last, in Arizona time, or how long it has been idle", () => {
    expect(status("live")).toEqual({ text: "1 task · last 00:58", stuck: false, idle: false });
    expect(status("idle")).toEqual({ text: "3 tasks · idle 3h05", stuck: false, idle: true });
  });
  it("never invents an idle age for a machine whose tasks have no recorded activity", () => {
    const f = world(flow("unseen", { last: null }));
    f.unseen.agents = agents(2);
    expect(rowMeta(f, "unseen", "in-progress", NOW).status).toEqual({ text: "2 tasks · no activity", stuck: false, idle: true });
  });
  it("says when a machine has no sessions, or only nested ones", () => {
    expect(status("empty").text).toBe("no sessions this hour");
    expect(status("only-nested").text).toBe("1 task nested · last 00:58");
  });
  it("counts the stuck rows for the header", () => {
    expect(stuckCount(flows, ["own", "above", "live", "idle"])).toBe(2);
  });
  it("writes an age as hours and minutes, or minutes", () => {
    expect([age(59), age(60), age(17 * 60), age(3600), age(4 * 3600 + 180)]).toEqual(["1m", "1m", "17m", "1h00", "4h03"]);
  });

  it("name the first row a top state opens, in the order the rows run, and none for a state no machine is entered from", () => {
    const flows = world(
      flow("late", { last: NOW - 900, ties: [tie("observed", "in-progress", "pr_opened", 3)] }),
      flow("soon", { last: NOW - 10, ties: [tie("declared", "in-progress", "pr_opened", null)] }),
      flow("other", { last: NOW, ties: [tie("observed", "in-progress", "working", 1)] }),
      flow("launched", { last: NOW - 5, ties: [tie("dag", null, null, null, "nightly")] }),
    );
    const rows = rankRows(flows, "in-progress");
    expect(firstOpened(flows, rows, "in-progress", "pr_opened")).toBe("soon");
    expect(firstOpened(flows, rows, "in-progress", "working")).toBe("other");
    expect(firstOpened(flows, rows, "in-progress", "review")).toBeNull();
  });
});
