// Types for the ported B · Suns engine (sunsEngine.js): the job it draws and the scene lists it fills.

/** One lens of a QA round: a verdict (PASS or CHANGES), or "pending" at a step of its own machine. */
export interface Lens {
  state: string;
  step: number;
}

/** One visit to a phase, oldest first; the last is the visit the task is in. */
export interface Visit {
  phase: string;
  round: number;
  mins: number;
  /** The lens verdicts a finished QA round reached. */
  v?: Record<string, string>;
  why?: string;
}

export interface Job {
  id: string;
  tier: "deep" | "standard" | "fast";
  title: string;
  spec: string;
  /** build, qa, deliver, review_fix, parked or done. */
  phase: string;
  step: number;
  round: number;
  limit: number;
  attended: boolean;
  /** Minutes in the current visit. */
  mins: number;
  lenses: Record<string, Lens>;
  plan: Record<string, string>;
  trail: Visit[];
}

export interface View {
  sel: string;
  open: Record<string, boolean>;
  pick: Record<string, string>;
  hover: string | null;
  det: string | null;
  /** Minutes back the board shows, or null for live. */
  at: number | null;
  replaying: boolean;
}

export interface Self {
  state: View;
  setState(patch: Partial<View>): void;
}

export interface Line {
  d: string;
  c: string;
  w: number;
  dash: string;
  op: number;
  st: string;
  cap: string;
}
export interface Box {
  style: string;
  text?: string;
  sub?: string;
  subColor?: string;
}
export interface Hit {
  aria: string;
  style: string;
  pick: () => void;
  text?: string;
}
export interface Hover extends Hit {
  enter: () => void;
  leave: () => void;
}
export interface Tip {
  x: number;
  y: number;
  t: string;
  lines: (string | false | null | undefined)[];
}
export interface Detail {
  title: string;
  sub: string;
  rows: { k: string; v: string; c?: string }[];
}

/** What one pass of the engine draws: paths, lines, glyphs, bodies, labels, badges, buttons, and the tips and details they open. */
export interface Scene {
  P: { lane: string[]; guide: string[]; grp: string[] };
  L: Line[];
  S: Box[];
  B: Box[];
  T: Box[];
  K: Box[];
  H: Hit[];
  Q: Hit[];
  V: Hover[];
  tips: Record<string, Tip>;
  dets: Record<string, Detail>;
  self: Self;
  open: View["open"];
  pick: View["pick"];
}

export const LENSES: string[];
export const LN: Record<string, string>;
export const PN: Record<string, string>;
export const STEPS: Record<string, string[]>;
export const TIER: Record<Job["tier"], string>;
export const STYLE: { note?: string } & Record<string, unknown>;
export const PANE_R: number;
export const HAIR: number;
/** Epoch ms until which a move is still animating. */
export const ANIM_UNTIL: number;
export function statusOf(j: Job): { t: string; c: string };
export function starfield(w: number, h: number, n: number): { style: string }[];
export function template(g: Scene, style: typeof STYLE, jobs: Job[], j: Job): void;
/** Draws the scrolling machine rows and answers their height. */
export function rows(g: Scene, style: typeof STYLE, j: Job): number;
export function hhmm(ago: number): string;
export function spanOf(j: Job): number;
export function jobAt(j: Job, ago: number | null): Job;
export function replay(g: Scene, j: Job, at: number | null, playing: boolean): void;
export function setNowMinutes(m: number): void;
