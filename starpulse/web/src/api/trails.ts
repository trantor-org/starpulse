// A flow's trails cross the wire as interned names and `[state, event, dt]` points; the page reads each step whole, so a snapshot or a move delta is decoded as it arrives.
import type { FlowSnapshot, MoveDelta, RawTask, Snapshot, TrailStep } from ".";
import type { FlowSnapshot as WireFlow, MoveDelta as WireMove, RawTask as WireAgent, Snapshot as WireSnapshot } from "./types.gen";

/** `points` as steps: the names `names` holds at each index, and a time that is the running sum of the dts, in milliseconds. */
function decodeTrail(points: NonNullable<WireAgent["trail"]>, names: readonly string[]): TrailStep[] {
  let ms = 0;
  return points.map(([state, event, dt, id]) => {
    ms += dt as number;
    return { state: names[state as number], event: names[event as number], at: ms / 1000, ...(id === undefined ? {} : { id: id as string }) };
  });
}

const decodeAgent = (agent: WireAgent, names: readonly string[]): RawTask =>
  (agent.trail ? { ...agent, trail: decodeTrail(agent.trail, names) } : agent) as RawTask;

const decodeFlow = (flow: WireFlow): FlowSnapshot =>
  (flow.names ? { ...flow, agents: flow.agents.map((a) => decodeAgent(a, flow.names!)) } : flow) as FlowSnapshot;

/** The snapshot as the page holds it: each flow's trails decoded. */
export const decodeSnapshot = (snap: WireSnapshot): Snapshot => ({ ...snap, flows: snap.flows.map(decodeFlow) });

/** The move delta as the page folds it: the agent's trail decoded through the delta's own names. */
export const decodeMove = (delta: WireMove): MoveDelta => ({ ...delta, agent: decodeAgent(delta.agent, delta.names ?? []) });

/** `held` with each of `added` it lacks, in order: a name a delta brings that the flow's table has not met joins it. */
export const intern = (held: string[] | null | undefined, added: string[] | null | undefined): string[] | undefined => {
  const fresh = (added ?? []).filter((name) => !held?.includes(name));
  return fresh.length ? [...(held ?? []), ...fresh] : (held ?? undefined);
};
