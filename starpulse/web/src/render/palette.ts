// The Star Map's colors. Every one is a role or neutral of the chosen theme, read from the :root tokens the theme core writes
// (readTokens); the exports below are live bindings, repainted when `sp:theme` fires, so a draw call that names one always gets the
// theme's current color. Before the first theme is applied (a test, an early paint) the StarPulse pack on Slate stands in.
import { readTokens } from "../features/admin/theme/apply";
import { hex, lch, mixLch } from "../features/admin/theme/color";
import { BUILTIN, SLATE, build } from "../features/admin/theme/scheme";
import type { Tokens } from "../features/admin/theme/themeStore";

let fallback: Tokens | null = null;
let held: Tokens | null = null;

/** A theme token's value (`run`, `ink-2`, `agent-text`, ...). */
export function token(name: string): string {
  held ??= { ...(fallback ??= build(BUILTIN.starpulse, SLATE).t), ...readTokens() };
  return held[name];
}

/** Two tokens mixed in OKLCH, `t` of the way from `a` to `b`: a shade between two roles, never a color of its own. */
export const mix = (a: string, b: string, t: number): string => hex(mixLch(lch(token(a)), lch(token(b)), t));

const hooks: (() => void)[] = [];
/** Runs `fn` now and after every theme change, in the order registered. */
export function onTheme(fn: () => void): void {
  hooks.push(fn);
  fn();
}
if (typeof window !== "undefined") {
  window.addEventListener("sp:theme", () => {
    held = null;
    for (const fn of hooks) fn();
  });
}

/** Activity: everything that moves on any level uses this one colour; the colour of a traced path, and of the cue for a hop with no line, is the same. */
export let ACT = "", TRACE = "";
/** A hop that is refused or fails. */
export let OFF = "";
/** A mapped machine (machine.source: a third party moves it) is drawn like a local one, in a colour of its own: the Ready blue, never purple. */
export let EXT = "";
/** A phase machine is the phase role; a sub-machine a phase opens is the submachine role. */
export let PHASE = "", SUBM = "", PHASE_TEXT = "", SUBM_TEXT = "";
/** A node's printed name, and the grey of its second line. */
export let LABEL = "", MUTED = "";
/** A lifecycle machine, and a planet; a moon; a Review sun and a sub-state: the agent's violet, its lighter text shade, and a shade toward fail. */
export let MACHINE = "", MOON = "", REVIEW = "";
/** A DAG run's, or a step's, colour by its state. */
export const DAG_COLOR: Record<string, string> = {};
/** A Board state's sun by its id. */
export const BOARD_COLOR: Record<string, string> = {};
/** The nine stops a machine ledger's rows walk from the first state to the last. */
export const RAMP: string[] = [];

/** An agent is coloured by the tier its profile names (`@agent-<tier>-<effort>`); a person or fast is the other colour. */
export const tierColor = (profile = "") =>
  profile.startsWith("@agent-deep") ? token("agent-text") : profile.startsWith("@agent-standard") ? token("waits") : token("run-text");

onTheme(() => {
  [ACT, TRACE, OFF, EXT] = [token("run"), token("run"), token("fail"), token("ready")];
  [PHASE, SUBM, PHASE_TEXT, SUBM_TEXT] = [token("phase"), token("submachine"), token("phase-text"), token("submachine-text")];
  [LABEL, MUTED] = [token("ink-2"), token("slate")];
  [MACHINE, MOON, REVIEW] = [token("agent"), token("agent-text"), mix("agent", "fail", 0.3)];
  Object.assign(DAG_COLOR, {
    running: ACT, queued: token("ready-text"), succeeded: token("ok"), failed: token("fail"),
    aborted: MUTED, skipped: token("muted"), not_started: token("track"),
  });
  Object.assign(BOARD_COLOR, {
    new: MUTED, ready: EXT, waiting: ACT, blocked: OFF, intoprogress: MACHINE,
    review: REVIEW, verifying: mix("agent", "ok", 0.55), proposed: MUTED, needs_attention: token("muted"), done: token("ok"), completed: token("released"), archived: token("faint"),
  });
  RAMP.splice(0, RAMP.length, MUTED, EXT, mix("ready", "agent", 0.5), MACHINE, mix("agent", "fail", 0.15), REVIEW, mix("agent", "fail", 0.6), ACT, token("ok"));
});
