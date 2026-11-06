// The canvas draws only while something moves. A settled Board requests no
// animation frame at all; an input, a snapshot or the tab returning wakes it.

import { FLARE, PULSE, TRAVEL } from "./sky";

export interface FrameLoop {
  /** Draw a frame now-ish, and keep drawing while `animating()` holds. A no-op when a frame is already pending; `urgent` cuts a wait for the pace short. */
  wake(urgent?: boolean): void;
  stop(): void;
}

/** How long after the last pointer or key input the canvas still draws at the display's pace with motion off, in ms. */
export const INPUT_MS = 600;
/** With motion off and no recent input, the wait between frames, in ms. */
export const STILL_MS = 1000;
/** A requested frame that runs this long late belongs to a window that painted none meanwhile. */
export const STALL_MS = 3 * STILL_MS;

/** With motion on and a running DAG the only thing moving, the wait between frames, in ms: its pulse needs ~12 fps, not the display's rate. */
export const RUN_MS = 80;

/** The wait before the next frame: none while input is recent, else `RUN_MS` for a running DAG alone, none for other motion, `STILL_MS` with motion off. */
export const framePace = (motion: boolean, sinceInput: number, runsOnly = false): number =>
  sinceInput < INPUT_MS ? 0 : !motion ? STILL_MS : runsOnly ? RUN_MS : 0;

export function frameLoop(opts: {
  draw(now: number): void;
  /** Whether another frame is needed after the one just drawn. */
  animating(): boolean;
  /** Called once each time the loop settles, after its last frame. */
  idle?(): void;
  request?(cb: (now: number) => void): number;
  cancel?(id: number): void;
  /** The wait in ms before each frame is requested; none by default. */
  pace?(): number;
}): FrameLoop {
  const { draw, animating, idle, request = (cb) => requestAnimationFrame(cb), cancel = (id) => cancelAnimationFrame(id), pace = () => 0 } = opts;
  let id = 0, wait: ReturnType<typeof setTimeout> | undefined, stopped = false;
  const schedule = (ms: number) => {
    if (ms <= 0) id = request(step);
    else
      wait = setTimeout(() => {
        wait = undefined;
        id = request(step);
      }, ms);
  };
  const step = (now: number) => {
    id = 0;
    draw(now);
    if (animating()) schedule(pace());
    else idle?.();
  };
  return {
    wake(urgent = false) {
      if (stopped) return;
      if (urgent && wait !== undefined) {
        clearTimeout(wait);
        wait = undefined;
      }
      if (!id && wait === undefined) schedule(urgent ? 0 : pace());
    },
    stop() {
      stopped = true;
      clearTimeout(wait);
      wait = undefined;
      if (id) cancel(id);
      id = 0;
    },
  };
}

/** What can move on its own: the clocks and runs the page reads, and the two transitions the page drives. */
export interface Motion {
  /** Epoch seconds. */
  now: number;
  moves: readonly { at: number }[];
  dags: readonly { status: string; finishedAt: string; active?: readonly { status: string }[] | null }[];
  /** A fly-to is easing the view. */
  flying: boolean;
  /** A level transition is running. */
  transitioning: boolean;
}

/** A move travels, then pulses on arrival; one queued for later counts so it plays when due. */
const MOVE_S = Math.max(TRAVEL + PULSE, FLARE);

const running = (d: Motion["dags"][number]) => d.status === "running" || !!d.active?.some((r) => r.status === "running");

/** Motion that needs the display's pace: a task move in flight or queued, a just-finished DAG, a fly-to, a transition. */
const driven = (m: Motion) => m.flying || m.transitioning || m.moves.some((e) => m.now - e.at < MOVE_S) || m.dags.some((d) => m.now - Date.parse(d.finishedAt) / 1000 < FLARE);

/** Whether anything needs the next frame: `driven` motion or a running (in any of its runs) DAG. */
export const animating = (m: Motion): boolean => driven(m) || m.dags.some(running);

/** Whether a running DAG is all that moves, so its frames may run at `RUN_MS`. */
export const runsOnly = (m: Motion): boolean => !driven(m) && m.dags.some(running);
