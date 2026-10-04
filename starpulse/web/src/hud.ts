// What the React HUD shows. The renderer writes it only when something changed,
// so the HUD re-renders on events, not on every animation frame.
import { useSyncExternalStore } from "react";
import type { KanbanTask } from "./kanban";
import { BOARD, type Path, type Tree } from "./levels";

/** One line of the activity feed: a move, or a DAG run ending. */
export interface FeedLine {
  key: string;
  /** When it happened, in seconds; the feed runs newest first. */
  at: number;
  time: string;
  who: string;
  what: string;
  where: string;
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
  /** Every DAG, which the navigator's filter opens in its panel. */
  dags: string[];
  /** The machines with a move in flight, so their navigator node glows. */
  moving: string[];
  /** The DAG domains the navigator's Constellations section flies to. */
  groups: { name: string; n: number }[];
  feed: FeedLine[];
  /** The Board's tasks as the Kanban view draws them, and the Board states' names. */
  cards: KanbanTask[];
  names: Record<string, string>;
  /** The Backlog board a task links into. */
  boardUrl: string | null;
}

export class HudStore {
  private state: HudState = {
    stats: "reading machine events…", live: "", path: BOARD, tree: null, states: [], counts: {}, dags: [],
    moving: [], groups: [], feed: [], cards: [], names: {}, boardUrl: null,
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
