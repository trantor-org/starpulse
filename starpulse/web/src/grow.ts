// A body's size follows its task count, and a snapshot can change that count at once. Each value a body draws at follows its
// target on a critically damped spring that settles within GROW_MS, so a state grows, shrinks or moves without jumping. The
// spring keeps its speed when the target changes mid-move, so snapshots arriving faster than one move lasts give one steady
// motion rather than a stop and a start on each.

export const GROW_MS = 1200;
const OMEGA = 7 / GROW_MS; // within 1% of a new target GROW_MS after it was set
const MAX_STEP = 32; // ms: a hidden tab's long frame steps as one slow frame, never as a jump
const REST = 0.01;

interface Spring {
  x: number;
  v: number;
  to: number;
  t: number;
}
const resting = (s: Spring) => s.x === s.to && s.v === 0;

/** Moves `s` `dt` ms toward its target: the exact critically damped step, so any frame length is stable. */
function step(s: Spring, dt: number) {
  const e = s.x - s.to;
  const k = Math.exp(-OMEGA * dt);
  const c = s.v + OMEGA * e;
  s.x = s.to + (e + c * dt) * k;
  s.v = (s.v - OMEGA * c * dt) * k;
  if (Math.abs(s.x - s.to) < REST && Math.abs(s.v) * 16 < REST) {
    s.x = s.to;
    s.v = 0;
  }
}

export function sizes() {
  const at = new Map<string, Spring>();
  return {
    /** The value to draw `key` at `now` (ms) for a target of `r`: `r` the first time, else stepped from what it showed toward `r`. */
    of(key: string, r: number, now: number): number {
      const s = at.get(key);
      if (!s) {
        at.set(key, { x: r, v: 0, to: r, t: now });
        return r;
      }
      const dt = resting(s) ? 0 : Math.min(now - s.t, MAX_STEP);
      s.t = now;
      s.to = r;
      if (dt > 0) step(s, dt);
      return s.x;
    },
    /** Whether any value is still moving, so the canvas draws another frame. */
    growing(): boolean {
      for (const s of at.values()) if (!resting(s)) return true;
      return false;
    },
  };
}
