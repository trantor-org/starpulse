// How each lifecycle machine is entered, where it nests, when it was last active and what is stuck in it, from the machines and their tasks.
// The In Progress machine is the Board's first submachine and the page draws it across the top; every machine entered from it is a row.

import type { FlowSnapshot, Stuck, Tie } from ".";

/** A task idle in a working state for longer than this (seconds) is stuck. */
export const STUCK_S = 7200;

export interface Derived {
  ties: Tie[];
  parent: string | null;
  depth: number;
  chain: string[];
  nested: string[];
  last: number | null;
  stuck: Stuck | null;
}

type Flow = Pick<FlowSnapshot, "name" | "machine" | "agents">;

/**
 * Each machine but the Board's `ties` (where it is entered from: declared by a `Submachine` on another machine's state, or a DAG launch,
 * declared ones first), `parent` (the machine its leading declared tie enters it from, else the In Progress machine), `depth`, `chain`
 * (the machines above it, outermost first), `nested` (every machine below it), `last` (when its newest task, or one nested below,
 * last moved) and `stuck` (the task of those idle longest past STUCK_S outside a final state), by machine name. With no In Progress
 * machine nothing nests.
 */
export function deriveTies(flows: Flow[], now: number): Record<string, Derived> {
  const machines = new Map(flows.filter((f) => f.name !== "board").map((f) => [f.name, f]));
  const board = flows.find((f) => f.name === "board")?.machine;
  const first = board?.submachines?.[0]?.machine;
  const ip = first && machines.has(first) ? first : null;

  const found: { child: string; tie: Tie }[] = [];
  const add = (child: string, machine: string | null, state: string | null, kind: Tie["kind"], dag: string | null, when = "") => {
    if (!found.some((t) => t.child === child && t.tie.kind === kind && t.tie.machine === machine && t.tie.state === state && t.tie.dag === dag))
      found.push({ child, tie: { kind, machine, state, dag, when } });
  };
  for (const [name, f] of machines)
    for (const link of f.machine.submachines ?? []) if (machines.has(link.machine) && link.machine !== ip) add(link.machine, name, link.state, "declared", null, link.when ?? "");
  for (const [dag, launch] of Object.entries(board?.launches ?? {})) {
    const child = [launch.machine, launch.skill].find((n): n is string => !!n && machines.has(n));
    if (child) add(child, null, null, "dag", dag);
  }
  const of = (child: string) => {
    const mine = found.filter((t) => t.child === child).map((t) => t.tie);
    return [...mine.filter((t) => t.kind !== "dag"), ...mine.filter((t) => t.kind === "dag")];
  };

  const up = new Map<string, string | null>([...machines.keys()].map((n) => [n, null]));
  if (ip !== null) {
    for (const name of machines.keys()) {
      const origin = of(name).find((t) => t.kind !== "dag")?.machine;
      up.set(name, origin && origin !== name && machines.has(origin) && origin !== ip ? origin : ip);
    }
    for (const name of machines.keys()) {
      if (name === ip) continue;
      let [seen, parent]: [number, string | null] = [0, up.get(name) ?? null];
      while (parent !== null && parent !== ip && parent !== name && seen < machines.size) [parent, seen] = [up.get(parent) ?? null, seen + 1];
      if (parent === name) up.set(name, ip); // a loop breaks to the In Progress machine
    }
  }
  const below = (name: string): string[] => [...machines.keys()].filter((c) => c !== ip && up.get(c) === name).flatMap((c) => [c, ...below(c)]);
  const chain = (name: string): string[] => {
    const parent = up.get(name) ?? null;
    return parent === null || parent === ip ? [] : [...chain(parent), parent];
  };
  const activity = (names: string[]) => {
    let last: number | null = null;
    let stuck: Stuck | null = null;
    for (const name of names) {
      const { machine, agents } = machines.get(name)!;
      const final = new Set(machine.states.filter((s) => s.final).map((s) => s.id));
      for (const { active, state } of agents) {
        if (active == null) continue;
        last = last === null ? active : Math.max(last, active);
        if (!final.has(state) && now - active > STUCK_S && (stuck === null || active < stuck.since)) stuck = { machine: name, state, since: active };
      }
    }
    return { last, stuck };
  };

  return Object.fromEntries(
    [...machines.keys()].map((name) => {
      const mine = name === ip ? [] : chain(name);
      const nested = below(name);
      return [name, { ties: of(name), parent: name === ip ? null : (up.get(name) ?? null), depth: name === ip ? 0 : mine.length + 1, chain: mine, nested, ...activity([name, ...nested]) }];
    }),
  );
}
