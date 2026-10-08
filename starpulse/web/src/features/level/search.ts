// The navigator's search: which suns, lifecycle machines and tasks a query
// names, and which body on the level showing stands for a result, so hovering
// the result can light it on the canvas. Pure; the renderer and the navigator own the rest.
import { pathTo, type Path, type Tree } from "../../render/levels";

export type Target =
  | { kind: "state"; id: string }
  | { kind: "machine"; flow: string; path: Path }
  | { kind: "task"; id: string; lane: string };
export interface Hit {
  target: Target;
  label: string;
  /** A task's title, under its id. */
  sub?: string;
  count?: number;
}
export interface Sources {
  tree: Tree;
  states: { id: string; name: string; count: number }[];
  counts: Record<string, number>;
  /** A machine's task count under one Board state, by `<state>/<flow>`. */
  hostCounts?: Record<string, number>;
  cards: { id: string; title: string; lane: string }[];
}

/** Every sun, machine and task the query names, in that order; nothing for a blank query. */
export function search(query: string, s: Sources): Hit[] {
  const q = query.trim().toLowerCase(), has = (...xs: string[]) => xs.some((x) => x.toLowerCase().includes(q));
  if (!q) return [];
  // a flow several Board states open is one result under each, told apart by the state's name
  const named = (id: string) => s.states.find((st) => st.id === id)?.name ?? id;
  const homes = Object.entries(s.tree.subs).flatMap(([state, flows]) => flows.map((flow) => ({ flow, state })));
  const kids = [...new Set(Object.values(s.tree.children).flat().map((c) => c.flow))].filter((flow) => !homes.some((h) => h.flow === flow));
  return [
    ...s.states.filter((st) => has(st.name)).map((st): Hit => ({ target: { kind: "state", id: st.id }, label: st.name, count: st.count })),
    ...homes.filter((h) => has(h.flow)).flatMap((h): Hit[] => {
      const path = pathTo(s.tree, h.flow, h.state), shared = homes.filter((o) => o.flow === h.flow).length > 1;
      return path ? [{ target: { kind: "machine", flow: h.flow, path }, label: h.flow, ...(shared && { sub: named(h.state) }), count: s.hostCounts?.[`${h.state}/${h.flow}`] ?? s.counts[h.flow] }] : [];
    }),
    ...kids.filter((m) => has(m)).flatMap((m): Hit[] => {
      const path = pathTo(s.tree, m);
      return path ? [{ target: { kind: "machine", flow: m, path }, label: m, count: s.counts[m] }] : [];
    }),
    ...s.cards.filter((c) => has(c.id, c.title)).map((c): Hit => ({ target: { kind: "task", id: c.id, lane: c.lane }, label: c.id, sub: c.title })),
  ];
}

/** The parts of a level's scene a result can stand for. */
export interface SpotScene {
  galaxies: Record<string, { id: string }>;
  sun: { id: string } | null;
  moons: { name: string }[];
  planets: { name: string }[];
  tasks: { id: string; gone: boolean }[];
  machineTasks: { id: string; _x?: number }[];
}
type Spot<S extends SpotScene> =
  | { kind: "galaxy"; o: S["galaxies"][string] }
  | { kind: "sun"; o: NonNullable<S["sun"]> }
  | { kind: "moon"; o: S["moons"][number] }
  | { kind: "planet"; o: S["planets"][number] }
  | { kind: "task"; o: S["tasks"][number] }
  | { kind: "mtask"; o: S["machineTasks"][number] };

/** The body on this level that stands for a result, as a hover over it would name it; null when the level does not draw it. */
export function spotIn<S extends SpotScene>(sc: S, t: Target): Spot<S> | null {
  const one = <K extends Spot<S>["kind"], O>(kind: K, o: O | null | undefined) => (o ? ({ kind, o } as Spot<S>) : null);
  switch (t.kind) {
    case "state":
      return one("galaxy", sc.galaxies[t.id]) ?? one("sun", sc.sun?.id === t.id ? sc.sun : null);
    case "machine": {
      // a machine on another page of its state's moons lights the state it opens under
      const under = t.path[1]?.kind === "state" ? sc.galaxies[t.path[1].id] : undefined;
      return one("moon", sc.moons.find((m) => m.name === t.flow)) ?? one("planet", sc.planets.find((p) => p.name === t.flow)) ?? one("galaxy", under);
    }
    case "task":
      return one("task", sc.tasks.find((k) => k.id === t.id && !k.gone)) ?? one("mtask", sc.machineTasks.find((k) => k.id === t.id && k._x !== undefined));
  }
}
