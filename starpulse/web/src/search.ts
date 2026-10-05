// The navigator's search: which suns, lifecycle machines, DAGs and tasks a query
// names, and which body on the level showing stands for a result, so hovering
// the result can light it on the canvas. Pure; the renderer and the navigator own the rest.
import { pathTo, type Path, type Tree } from "./levels";

export type Target =
  | { kind: "state"; id: string }
  | { kind: "machine"; flow: string; path: Path }
  | { kind: "dag"; name: string }
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
  dags: string[];
  cards: { id: string; title: string; lane: string }[];
}

/** Every sun, machine, DAG and task the query names, in that order; nothing for a blank query. */
export function search(query: string, s: Sources): Hit[] {
  const q = query.trim().toLowerCase(), has = (...xs: string[]) => xs.some((x) => x.toLowerCase().includes(q));
  if (!q) return [];
  const machines = [...new Set([...Object.values(s.tree.subs).flat(), ...Object.values(s.tree.children).flat().map((c) => c.flow)])];
  return [
    ...s.states.filter((st) => has(st.name)).map((st): Hit => ({ target: { kind: "state", id: st.id }, label: st.name, count: st.count })),
    ...machines.filter((m) => has(m)).flatMap((m): Hit[] => {
      const path = pathTo(s.tree, m);
      return path ? [{ target: { kind: "machine", flow: m, path }, label: m, count: s.counts[m] }] : [];
    }),
    ...s.dags.filter((d) => has(d)).map((d): Hit => ({ target: { kind: "dag", name: d }, label: d })),
    ...s.cards.filter((c) => has(c.id, c.title)).map((c): Hit => ({ target: { kind: "task", id: c.id, lane: c.lane }, label: c.id, sub: c.title })),
  ];
}

/** The parts of a level's scene a result can stand for. */
export interface SpotScene {
  galaxies: Record<string, { id: string }>;
  sun: { id: string } | null;
  moons: { name: string }[];
  planets: { name: string }[];
  stars: Record<string, { name: string; fold?: string[] }>;
  hangar?: { names: string[] } | null;
  tasks: { id: string; gone: boolean }[];
  machineTasks: { id: string; _x?: number }[];
}
type Spot<S extends SpotScene> =
  | { kind: "galaxy"; o: S["galaxies"][string] }
  | { kind: "sun"; o: NonNullable<S["sun"]> }
  | { kind: "moon"; o: S["moons"][number] }
  | { kind: "planet"; o: S["planets"][number] }
  | { kind: "dag"; o: S["stars"][string] }
  | { kind: "hangar"; o: NonNullable<S["hangar"]> }
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
    case "dag":
      return one("dag", Object.values(sc.stars).find((s) => s.name === t.name || s.fold?.includes(t.name))) ?? one("hangar", sc.hangar?.names.includes(t.name) ? sc.hangar : null);
    case "task":
      return one("task", sc.tasks.find((k) => k.id === t.id && !k.gone)) ?? one("mtask", sc.machineTasks.find((k) => k.id === t.id && k._x !== undefined));
  }
}
