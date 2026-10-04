// The page's level stack: Board, then a Board state's lifecycle system, then one
// machine (and a machine's child), the DAGs level of every DAG free of the Board,
// and a fold level over the Board path that several DAGs write. Pure: which
// machines open where, the path to any of them, what a click on a DAG opens,
// and where an old URL lands.
import type { Snapshot } from "./types";

/** The DAGs a Board fold stands for, the criteria that tie them to the Board and the two Board states of the path they write (null beside one state). */
export interface Fold {
  dags: string[];
  crit: string[];
  path: [string, string] | null;
}
export type Level = { kind: "board" } | { kind: "dags" } | { kind: "state"; id: string } | { kind: "machine"; flow: string } | ({ kind: "fold" } & Fold);
export type Path = Level[];
/** A machine that opens under one state of another machine. */
export interface Child {
  state: string;
  flow: string;
  when: string;
}
export interface Tree {
  /** The Board's state ids, in machine order. */
  states: string[];
  /** The lifecycle machines each Board state opens into; the first is the state's own sub-flow. */
  subs: Record<string, string[]>;
  /** The machines that open under a machine's states. */
  children: Record<string, Child[]>;
}
export const BOARD: Path = [{ kind: "board" }];

/**
 * Which machines open where, from a Board snapshot. The Board's sub-flows open
 * under their states; every other lifecycle machine is a skill a delivery
 * session runs, so it joins the state of the Board's first sub-flow.
 */
export function tree(snap: Pick<Snapshot, "graphs" | "flows">): Tree {
  const board = snap.flows.find((f) => f.name === "board")?.machine;
  const t: Tree = { states: board?.states.map((s) => s.id) ?? [], subs: {}, children: {} };
  const inner = new Set<string>();
  for (const link of board?.subflows ?? []) {
    (t.subs[link.state] ??= []).push(link.flow);
    inner.add(link.flow);
  }
  for (const f of snap.flows)
    for (const link of f.machine.subflows ?? [])
      if (link.parent !== "board") {
        (t.children[f.name] ??= []).push({ state: link.state, flow: link.flow, when: link.when });
        inner.add(link.flow);
      }
  const primary = board?.subflows?.[0]?.state;
  if (primary)
    for (const g of snap.graphs) if (g !== "board" && g !== "runs" && !inner.has(g)) t.subs[primary].push(g);
  return t;
}

/** The path down to a machine, or null when no level holds it. */
export function pathTo(t: Tree, flow: string): Path | null {
  if (flow === "board" || flow === "runs") return BOARD;
  for (const [state, subs] of Object.entries(t.subs))
    if (subs.includes(flow)) return [...BOARD, { kind: "state", id: state }, { kind: "machine", flow }];
  for (const [parent, kids] of Object.entries(t.children))
    if (kids.some((c) => c.flow === flow)) {
      const up = pathTo(t, parent);
      return up && [...up, { kind: "machine", flow }];
    }
  return null;
}

const same = (a: Path | null, b: Path) => JSON.stringify(a) === JSON.stringify(b);

/** Whether every level of a path still exists; a cached path can outlive a machine or a Board state. */
function valid(t: Tree, path: Path): boolean {
  if (path[0]?.kind !== "board") return false;
  const last = path[path.length - 1];
  if (last.kind === "machine") return same(pathTo(t, last.flow), path);
  if (last.kind === "state") return path.length === 2 && t.states.includes(last.id);
  if (last.kind === "dags") return path.length === 2;
  if (last.kind !== "fold") return false;
  return path.length === 2 && last.dags.length > 0 && (last.path ?? []).every((id) => t.states.includes(id));
}

/** What a click on a DAG body opens: a single DAG's panel beside the level, or a fold's own level over the path it writes. */
export function drill(o: { name: string; fold?: string[] }, crit: string[], path: [string, string] | null): { panel: string } | { push: Level } {
  return o.fold ? { push: { kind: "fold", dags: o.fold, crit, path } } : { panel: o.name };
}

/**
 * Where the page opens. A retired per-graph URL (`/board`, `/runs`,
 * `/flow/<name>`, `/#sec-<name>`) opens the level that draws its graph; the
 * root reopens the path this browser last showed, else the Board.
 */
export function startPath(pathname: string, hash: string, cached: Path | null, t: Tree): Path {
  const name = /^\/flow\/([^/]+)$/.exec(pathname)?.[1] ?? (pathname === "/" ? /^#sec-(.+)$/.exec(hash)?.[1] : pathname.slice(1));
  if (name) return pathTo(t, decodeURIComponent(name)) ?? BOARD;
  return cached && valid(t, cached) ? cached : BOARD;
}

/** A level's name as the navigator and the cache key show it. */
export const levelKey = (l: Level) => (l.kind === "board" ? "board" : l.kind === "dags" ? "dags" : l.kind === "state" ? l.id : l.kind === "machine" ? l.flow : l.dags.join("+"));
export const pathKey = (p: Path) => p.map(levelKey).join("/");
