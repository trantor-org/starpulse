import { describe, expect, it } from "vitest";
import { deriveTies, STUCK_S } from "./ties";

type Sub = { state: string; machine: string; when?: string };
const flow = (name: string, over: { submachines?: Sub[]; launches?: Record<string, { skill: string | null; machine: string | null }>; final?: string[]; agents?: { state: string; active: number | null }[] } = {}) =>
  ({
    name,
    agents: (over.agents ?? []).map((a, i) => ({ id: `${name}-${i}`, title: "", model: "", ...a })),
    machine: {
      name, states: [{ id: "work" }, ...(over.final ?? []).map((id) => ({ id, final: true }))], submachines: over.submachines ?? [], launches: over.launches ?? {},
    },
  }) as never;

describe("deriveTies", () => {
  const flows = [
    flow("board", { submachines: [{ state: "in_progress", machine: "in-progress" }], launches: { sweep: { skill: "auditing", machine: null }, tick: { skill: null, machine: "scheduler" } } }),
    flow("in-progress", { submachines: [{ state: "pr", machine: "triage", when: "a PR is open" }] }),
    flow("triage"),
    flow("auditing"),
    flow("scheduler"),
  ];

  it("takes the Board's first submachine as the In Progress machine, and nests a machine under the one that enters it, else under In Progress", () => {
    const d = deriveTies(flows, 0);

    expect([d["in-progress"].parent, d["in-progress"].depth, d.triage.parent, d.triage.depth, d.triage.chain, d.auditing.parent]).toEqual([null, 0, "in-progress", 1, [], "in-progress"]);
    expect(d["in-progress"].nested).toEqual(["triage", "auditing", "scheduler"]);
  });

  it("lists a declared tie before a DAG launch's, each with where it enters", () => {
    const d = deriveTies(flows, 0);

    expect(d.triage.ties).toEqual([{ kind: "declared", machine: "in-progress", state: "pr", dag: null, when: "a PR is open" }]);
    expect(d.auditing.ties).toEqual([{ kind: "dag", machine: null, state: null, dag: "sweep", when: "" }]);
    expect(d.scheduler.ties.map((t) => t.dag)).toEqual(["tick"]);
  });

  it("nothing nests without an In Progress machine", () => {
    const d = deriveTies([flow("board"), flow("triage")], 0);

    expect([d.triage.parent, d.triage.depth]).toEqual([null, 1]);
  });

  it("breaks a loop of declared ties back to the In Progress machine", () => {
    const loop = [flows[0], flows[1], flow("a", { submachines: [{ state: "x", machine: "b" }] }), flow("b", { submachines: [{ state: "x", machine: "a" }] })];

    const d = deriveTies(loop, 0);

    expect([d.a.parent, d.b.parent]).toEqual(["in-progress", "a"]);
  });

  it("reads when a machine, with those below it, was last active, and the task idle longest past STUCK_S outside a final state as stuck", () => {
    const now = 100_000;
    const busy = [
      flows[0],
      flow("in-progress", { submachines: [{ state: "pr", machine: "triage" }] }),
      flow("triage", { final: ["done"], agents: [{ state: "work", active: now - STUCK_S - 50 }, { state: "done", active: now - 10 * STUCK_S }, { state: "work", active: now - 5 }, { state: "work", active: null }] }),
    ];

    const d = deriveTies(busy, now);

    expect(d.triage.last).toBe(now - 5);
    expect(d.triage.stuck).toEqual({ machine: "triage", state: "work", since: now - STUCK_S - 50 });
    expect(d["in-progress"].last).toBe(now - 5);
    expect(d["in-progress"].stuck?.machine).toBe("triage");
  });
});
