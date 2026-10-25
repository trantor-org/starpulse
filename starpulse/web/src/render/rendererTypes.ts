import type { Target } from "../features/level/search";
import type { Path } from "./levels";
import type { Pt } from "./scene";
import type { View } from "./zoom";

/** What the Playwright probe reads: the level, where its box sits on screen, and what a click there opens. */
export interface Probe {
  path: string;
  /** Whether a snapshot has arrived and no transition or fly-to is running. */
  ready: boolean;
  /** The canvas the level is centred in; an open panel floats over it. */
  canvas: { w: number; h: number };
  /** Whether a click panel is open. */
  panel: boolean;
  centre: Pt;
  zoomed: boolean;
  /** What a click opens: another level, or a panel beside this one. */
  targets: { name: string; opens: "level" | "panel" | "none"; x: number; y: number }[];
  /** The level's fit zoom. */
  fit: number;
  /** Board only: each state's screen disc. */
  states: { id: string; x: number; y: number; r: number; sun?: number; edge?: number }[];
  /** The Board's drawn curves on screen, sampled from source to target. */
  edges?: { s: string; t: string; pts: { x: number; y: number }[] }[];
  /** Each task dot's screen position, to hover one. */
  tasks?: { id: string; x: number; y: number }[];
  /** Each drawn phase branch's own line on screen, for the overlap check. */
  branches?: { key: string; sun: string; ring: number; parent?: string; th?: number; lane?: number; dir?: number; n?: number; pj?: number; pts: { x: number; y: number }[] }[];
  /** Each printed name meeting another name or a station, as `a~b` or `name@branch`. */
  texts?: string[];
}

export interface Renderer {
  start(): void;
  stop(): void;
  /** Open a level; the old one zooms through (fx, fy). `then` gives the view to land on. */
  go(path: Path, fx?: number, fy?: number, then?: () => View): void;
  /** Fly back to the level's fit. */
  fitView(): void;
  /** Whether the Star Map is the view showing; while another view hides it, the canvas draws no frame. */
  show(on: boolean): void;
  /** Light the body a navigator search result stands for, as a hover over it would; null clears it. With `near`, a task the level does not draw lights its state instead. */
  spot(target: Target | null, near?: boolean): void;
  /** Open a task's panel on the level showing: pinned, as a click on it would, where the level draws it, else its Board panel. */
  openTask(id: string): void;
  /** Pin a task on the Board and open its panel, as a click on it would. */
  selectTask(id: string): void;
  /** The Admin view changed how times are written: write the subtitle, the Recent feed and the header clock again. */
  refresh(): void;
}
