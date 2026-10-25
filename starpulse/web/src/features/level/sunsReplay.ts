// The drill-in's replay: where each machine of a task stood at a time in its last 24 hours, and the scrubber that moves that time. Pure; the page
// feeds it /api/history?task=&hours=24 (TASK-8664) and the clock. The scrubber starts live and nothing replays until it is moved.
import type { MachineEvent } from "../../api/types.gen";

export type { MachineEvent };

export const WINDOW = 24 * 3600;
/** Replay seconds that pass per second of the page's: 24 hours play in four minutes. */
export const SPEED = 360;

export interface Replay {
  live: boolean;
  playing: boolean;
  /** Epoch seconds the board shows. */
  t: number;
}
export interface Stand {
  state: string;
  at: number;
  from: string;
}

export const startReplay = (now: number): Replay => ({ live: true, playing: false, t: now });
export const goLive = (_: Replay, now: number): Replay => startReplay(now);
export const play = (s: Replay): Replay => (s.live ? s : { ...s, playing: true });
export const pause = (s: Replay): Replay => ({ ...s, playing: false });

/** Move to `t`, held inside the window; at or past now it is live. */
export function scrubTo(s: Replay, t: number, now: number): Replay {
  return t >= now ? goLive(s, now) : { live: false, playing: false, t: Math.max(t, now - WINDOW) };
}
/** Advance a playing replay by `dt` page seconds; it returns to live on reaching now. */
export function replayStep(s: Replay, dt: number, now: number): Replay {
  if (s.live || !s.playing) return s;
  const t = s.t + dt * SPEED;
  return t >= now ? goLive(s, now) : { ...s, t };
}

/** Each machine's state at `t`: its last event at or before it. A machine with none yet is absent. */
export function stateAt(events: MachineEvent[], t: number): Record<string, Stand> {
  const at: Record<string, Stand> = {};
  for (const e of events) if (e.at <= t) at[e.machine] = { state: e.to, at: e.at, from: e.from };
  return at;
}
/** The events after `t0` up to `t1`: the moves a step crosses, which alone animate. */
export const movesBetween = (events: MachineEvent[], t0: number, t1: number): MachineEvent[] => events.filter((e) => e.at > t0 && e.at <= t1);
