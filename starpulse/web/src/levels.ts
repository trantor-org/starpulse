// The page's level stack: Board, then a Board state's lifecycle system, then one
// machine (and a machine's child), the DAGs level of every DAG free of the Board,
// and a fold level over the Board path that several DAGs write. Pure: which
// machines open where, the path to any of them, what a click on a DAG opens,
// and where an old URL lands.
import { pathOf, tiesOf, type Source } from "./ledger";
import type { Snapshot } from "./types";

/** The DAGs a Board fold stands for, the criteria that tie them to the Board and the two Board states of the path they write (null beside one state). */
export interface Fold {
  dags: string[];
  crit: string[];
  path: [string, string] | null;
  /** The Board event whose Ledger the fold is, when it was opened from one; else the Ledger names it from the path and the DAGs. */
  event?: string;
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
  /** Each mapped machine's third-party source, by flow name. */
  sources?: Record<string, string>;
}
export const BOARD: Path = [{ kind: "board" }];

/**
 * Which machines open where, from a Board snapshot. The Board's sub-flows open
 * under their states; every other lifecycle machine is a skill a delivery
 * session runs, so it joins the state of the Board's first sub-flow.
 */
export function tree(snap: Pick<Snapshot, "graphs" | "flows">): Tree {
  const board = snap.flows.find((f) => f.name === "board")?.machine;
  const t: Tree = { states: board?.states.map((s) => s.id) ?? [], subs: {}, children: {}, sources: {} };
  for (const f of snap.flows) if (f.machine.source) t.sources![f.name] = f.machine.source;
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

/** A machine task's kicker line on its tooltip and panel; a task on a mapped machine names the third party that moves it. */
export const taskKicker = (flow: string, state: string, source?: string): string => `task · ${flow}${source ? ` · mapped from ${source}` : ""} · ${state}`;

/** The Board state a path runs under, which scopes the tasks a machine level shows; undefined above any state. */
export const hostOf = (path: Path): string | undefined => path.find((l): l is Extract<Level, { kind: "state" }> => l.kind === "state")?.id;

/**
 * The path down to a machine, or null when no level holds it. A flow several Board states open is one level
 * under each, so `host` picks the (state, flow) pair; without it the first host that opens the flow answers.
 */
export function pathTo(t: Tree, flow: string, host?: string): Path | null {
  if (flow === "board" || flow === "runs") return BOARD;
  for (const [state, subs] of Object.entries(t.subs))
    if ((host === undefined || state === host) && subs.includes(flow)) return [...BOARD, { kind: "state", id: state }, { kind: "machine", flow }];
  for (const [parent, kids] of Object.entries(t.children))
    if (kids.some((c) => c.flow === flow)) {
      const up = pathTo(t, parent, host);
      return up && [...up, { kind: "machine", flow }];
    }
  return null;
}

/**
 * The machine drawn across the top of a level: drilling the Board state that opens a primary machine puts that machine on top, as the head
 * of its machine ledger. Null on every other level.
 */
export const topOf = (subs: Record<string, string[]>, l: Level): string | null => (l.kind === "state" ? (subs[l.id]?.[0] ?? null) : null);

const same = (a: Path | null, b: Path) => JSON.stringify(a) === JSON.stringify(b);

/** Whether every level of a path still exists; a cached path can outlive a machine or a Board state. */
function valid(t: Tree, path: Path): boolean {
  if (path[0]?.kind !== "board") return false;
  const last = path[path.length - 1];
  if (last.kind === "machine") return same(pathTo(t, last.flow, hostOf(path)), path);
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

/** The fold level that is a Board transition's Ledger: the DAGs that write its event or are cued by it, over the path it takes; null when no DAG is tied to it or it leaves its state where it was. */
export function ledgerLevel(snap: Source, event: string): ({ kind: "fold" } & Fold) | null {
  const path = pathOf(snap, event), ties = tiesOf(snap, event);
  if (!path || !ties.length) return null;
  const name = (id: string) => snap.flows.find((f) => f.name === "board")?.machine.states.find((s) => s.id === id)?.name || id, via = `(${name(path[0])} → ${name(path[1])})`;
  return { kind: "fold", event, path, dags: ties.map((t) => t.dag), crit: ties.map((t) => `${t.dag}: ${t.role === "writer" ? `writes ${event}` : `runs on ${t.on}, beside ${event}`} ${via}`) };
}

/** The Ledger a Board path opens: that of the first of its events a DAG is tied to. */
export const pathLedger = (snap: Source, events: string[]) => events.map((e) => ledgerLevel(snap, e)).find((l) => l) ?? null;
