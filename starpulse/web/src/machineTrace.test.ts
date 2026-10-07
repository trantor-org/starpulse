import { describe, expect, it } from "vitest";
import { sessionsOf, traceSteps } from "./machineTrace";
import type { FlowSnapshot, RawAgent } from "./types";

/** A machine whose states run in a line, `a → b → c`, with no line back. */
function flow(name: string, ids: string[], agents: RawAgent[] = []): FlowSnapshot {
  return {
    name,
    machine: { states: ids.map((id, i) => ({ id, name: id, initial: !i, final: i === ids.length - 1 })), transitions: ids.slice(1).map((t, i) => ({ source: ids[i], target: t, event: t })) },
    agents,
    ties: [],
    parent: name === "in-progress" ? null : "in-progress",
    depth: name === "in-progress" ? 0 : 1,
    chain: [],
    nested: [],
    last: null,
    stuck: null,
  };
}
/** A session of `task` that held each state from the time beside it. */
const session = (task: string | null, ...trail: [string, number][]): RawAgent => ({
  id: `${task}-${trail[0][1]}`, title: "", model: "", task, state: trail.at(-1)![0], trail: trail.map(([state, at]) => ({ state, event: state.toUpperCase(), at })), active: trail.at(-1)![1],
});
const everywhere = () => true;
const steps = (flows: Record<string, FlowSnapshot>, task: string, has: (s: { machine: string; state: string }) => boolean = everywhere) => {
  const agent = Object.values(flows).flatMap((f) => f.agents).find((a) => a.task === task)!, at = Object.values(flows).find((f) => f.agents.includes(agent))!.name;
  return traceSteps(flows, sessionsOf(flows, at, agent), "in-progress", has).map((s) => `${s.n} ${s.kind} ${s.a.machine}:${s.a.state}>${s.b.machine}:${s.b.state}${s.off ? " off" : ""}`);
};
const world = (...fs: FlowSnapshot[]) => Object.fromEntries(fs.map((f) => [f.name, f]));

describe("a task's path across the machine ledger", () => {
  const flows = world(
    flow("in-progress", ["start", "ready", "opened"], [session("T-1", ["start", 100], ["ready", 200], ["opened", 500]), session("T-2", ["start", 100])]),
    flow("drafting", ["draft", "tested"], [session("T-1", ["draft", 250], ["tested", 300])]),
    flow("reviewing", ["review", "green"], [session("T-1", ["review", 1000], ["green", 1100])]),
  );

  it("spans each row the task has a session in, numbered in session order, each entry dropping from the state the task held in the template", () => {
    expect(steps(flows, "T-1")).toEqual([
      "1 hop in-progress:start>in-progress:ready",
      "2 entry in-progress:ready>drafting:draft",
      "3 hop drafting:draft>drafting:tested",
      "4 hop in-progress:ready>in-progress:opened",
      "5 entry in-progress:opened>reviewing:review",
      "6 hop reviewing:review>reviewing:green",
    ]);
  });

  it("enters a row from another row whose session was still open then, the newest of them", () => {
    const nested = world(
      ...Object.values(flows),
      flow("evals", ["run", "pass"], [session("T-1", ["run", 320], ["pass", 330])]),
      flow("linting", ["lint", "clean"], [session("T-1", ["lint", 1050])]),
    );
    const s = steps(nested, "T-1");
    expect(s).toContain("4 entry drafting:tested>evals:run");
    expect(s).toContain("8 entry reviewing:review>linting:lint");
  });

  it("bows a hop off its machine's lines when the machine has no line for it", () => {
    const loop = world(flow("in-progress", ["start", "ready", "opened"], [session("T-3", ["start", 10], ["opened", 20], ["ready", 30])]));
    expect(steps(loop, "T-3")).toEqual(["1 hop in-progress:start>in-progress:opened off", "2 hop in-progress:opened>in-progress:ready off"]);
  });

  it("leaves out a step to a state the ledger does not draw, and numbers the rest", () => {
    expect(steps(flows, "T-1", (s) => s.machine !== "drafting")).toEqual([
      "1 hop in-progress:start>in-progress:ready",
      "2 hop in-progress:ready>in-progress:opened",
      "3 entry in-progress:opened>reviewing:review",
      "4 hop reviewing:review>reviewing:green",
    ]);
  });

  it("traces a session with no task as only itself", () => {
    const solo = world(flow("in-progress", ["start", "ready"]), flow("drafting", ["draft", "tested"], [session(null, ["draft", 5], ["tested", 9]), session(null, ["draft", 6])]));
    const agent = solo.drafting.agents[0];
    expect(sessionsOf(solo, "drafting", agent)).toEqual([{ machine: "drafting", agent }]);
    expect(traceSteps(solo, sessionsOf(solo, "drafting", agent), "in-progress", everywhere).map((s) => s.kind)).toEqual(["hop"]);
  });
});
