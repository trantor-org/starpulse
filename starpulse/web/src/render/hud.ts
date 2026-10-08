// What the React HUD shows. The renderer writes it only when something changed,
// so the HUD re-renders on events, not on every animation frame.
import { useSyncExternalStore } from "react";
import type { KanbanTask } from "../features/kanban/kanban";
import { BOARD, type Path, type Tree } from "./levels";
import type { DagData } from "../features/dags/dags";
import type { Capabilities, Pool } from "../api";

/** One line of the activity feed: a move, a DAG run ending, or a run starting, queueing, changing step or ending. */
export interface FeedLine {
  key: string;
  /** When it happened, in seconds; the feed runs newest first. */
  at: number;
  time: string;
  who: string;
  what: string;
  where: string;
  /** A run's outcome: green when it succeeded, red when it failed. */
  tone?: "ok" | "failed";
  /** Born after the page's first read: the feed flashes it once. */
  fresh?: boolean;
  /** The task the line is about, which hovering it lights and clicking it opens. */
  task?: string;
  /** The DAG that wrote it, which the line lights on the Star Map when it names no task. */
  dag?: string;
}
export interface BoardState {
  id: string;
  name: string;
  count: number;
}
export interface HudState {
  stats: string;
  live: "" | "on" | "off";
  /** The level the page shows. */
  path: Path;
  tree: Tree | null;
  states: BoardState[];
  /** Tasks per machine; the Board's are its open tasks. */
  counts: Record<string, number>;
  /** Tasks per machine at one Board state, by `<state>/<flow>`: a flow several states open shows each its own. */
  hostCounts: Record<string, number>;
  /** Every DAG, which the navigator's search finds and opens in its panel. */
  dags: string[];
  /** The machines with a move in flight, so their navigator node glows. */
  moving: string[];
  /** The snapshot's DAGs with their domains, pools, cues and machines, which the DAGs view draws; null before the first read. */
  dagData: DagData | null;
  /** The DAG domains the navigator's DAGs section flies to. */
  /** The concurrency pools the navigator's Queues section lists; empty when the adapter reports none. */
  pools: Pool[];
  feed: FeedLine[];
  /** The Board's tasks as the Kanban view draws them, and the Board states' names. */
  cards: KanbanTask[];
  names: Record<string, string>;
  /** Each task's latest refused claim, which returns a card the view started a session for. */
  claims: Record<string, { reason: string; at: number }>;
  /** The Backlog board a task links into. */
  boardUrl: string | null;
  /** What the board writes beyond moves: the task view draws Edit and Archive… only for what it can. */
  capabilities?: Capabilities;
  /** The Backlog.md project serve found beside the config while it shows its own board, and how to switch to it. */
  hint?: string | null;
}

export class HudStore {
  private state: HudState = {
    stats: "reading machine events…", live: "", path: BOARD, tree: null, states: [], counts: {}, hostCounts: {}, dags: [], dagData: null,
    moving: [], pools: [], feed: [], cards: [], names: {}, claims: {}, boardUrl: null,
  };
  private listeners = new Set<() => void>();

  get = () => this.state;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  set(patch: Partial<HudState>) {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn();
  }
}

export const useHud = (store: HudStore) => useSyncExternalStore(store.subscribe, store.get);
