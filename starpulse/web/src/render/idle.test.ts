import { describe, expect, it } from "vitest";
import { afterEach, vi } from "vitest";
import { INPUT_MS, STILL_MS, animating, frameLoop, framePace, type Motion } from "./idle";
import { FLARE, PULSE, TRAVEL } from "./sky";

/** A frame scheduler the test steps by hand, counting every request. */
function scheduler() {
  const pending = new Map<number, (now: number) => void>();
  let next = 1, requests = 0;
  return {
    request: (cb: (now: number) => void) => {
      requests++;
      pending.set(next, cb);
      return next++;
    },
    cancel: (id: number) => void pending.delete(id),
    frame(now = 0) {
      const due = [...pending.values()];
      pending.clear();
      for (const cb of due) cb(now);
    },
    get requests() {
      return requests;
    },
    get pending() {
      return pending.size;
    },
  };
}

function loop(busy: { on: boolean }) {
  const s = scheduler();
  const drawn: number[] = [];
  let idled = 0;
  const l = frameLoop({
    draw: (now) => void drawn.push(now),
    animating: () => busy.on,
    idle: () => void idled++,
    request: s.request,
    cancel: s.cancel,
  });
  return { s, l, drawn, idled: () => idled };
}

describe("frameLoop", () => {
  it("requests no frame until woken", () => {
    const { s } = loop({ on: false });

    expect(s.requests).toBe(0);
  });

  it("draws one frame when woken at rest and then requests no more", () => {
    const { s, l, drawn } = loop({ on: false });

    l.wake();
    s.frame(10);
    s.frame(20);

    expect(drawn).toEqual([10]);
    expect(s.requests).toBe(1);
    expect(s.pending).toBe(0);
  });

  it("keeps requesting frames while something animates and stops when it settles", () => {
    const busy = { on: true };
    const { s, l, drawn } = loop(busy);

    l.wake();
    s.frame(1);
    s.frame(2);
    busy.on = false;
    s.frame(3);
    s.frame(4);

    expect(drawn).toEqual([1, 2, 3]);
    expect(s.requests).toBe(3);
  });

  it("says once when it goes idle", () => {
    const busy = { on: true };
    const { s, l, idled } = loop(busy);

    l.wake();
    s.frame();
    expect(idled()).toBe(0);
    busy.on = false;
    s.frame();
    s.frame();

    expect(idled()).toBe(1);
  });

  it("does not stack a second request when woken with a frame already pending", () => {
    const { s, l } = loop({ on: false });

    l.wake();
    l.wake();
    l.wake();

    expect(s.requests).toBe(1);
  });

  it("starts again when woken after it went idle", () => {
    const { s, l, drawn } = loop({ on: false });
    l.wake();
    s.frame(1);

    l.wake();
    s.frame(2);

    expect(drawn).toEqual([1, 2]);
  });

  it("cancels a pending frame on stop and ignores a later wake", () => {
    const { s, l, drawn } = loop({ on: true });
    l.wake();

    l.stop();
    s.frame();
    l.wake();
    s.frame();

    expect(drawn).toEqual([]);
    expect(s.requests).toBe(1);
  });
});

describe("animating", () => {
  const rest: Motion = { now: 1000, moves: [], dags: [], flying: false, transitioning: false };
  const ago = (s: number) => new Date((rest.now - s) * 1000).toISOString();

  it("is false for a settled board", () => {
    const old = { at: rest.now - 600 };
    const dag = { status: "succeeded", finishedAt: ago(600) };

    expect(animating({ ...rest, moves: [old], dags: [dag] })).toBe(false);
  });

  it("is true while a task travels and while it pulses on arrival", () => {
    expect(animating({ ...rest, moves: [{ at: rest.now - TRAVEL + 0.1 }] })).toBe(true);
    expect(animating({ ...rest, moves: [{ at: rest.now - TRAVEL - PULSE + 0.1 }] })).toBe(true);
  });

  it("is true for a move queued to start later, so it plays on time", () => {
    expect(animating({ ...rest, moves: [{ at: rest.now + 5 }] })).toBe(true);
  });

  it("is true while a DAG runs and while its finish flares", () => {
    expect(animating({ ...rest, dags: [{ status: "running", finishedAt: "" }] })).toBe(true);
    expect(animating({ ...rest, dags: [{ status: "succeeded", finishedAt: ago(FLARE - 0.5) }] })).toBe(true);
  });

  it("is true while any of a DAG's runs is running, whatever its latest run did", () => {
    const old = { status: "succeeded", finishedAt: ago(FLARE + 60) };
    expect(animating({ ...rest, dags: [{ ...old, active: [{ status: "running" }] }] })).toBe(true);
    expect(animating({ ...rest, dags: [{ ...old, active: [{ status: "queued" }] }] })).toBe(false);
    expect(animating({ ...rest, dags: [{ ...old, active: [] }] })).toBe(false);
  });

  it("is true during a fly-to and a level transition", () => {
    expect(animating({ ...rest, flying: true })).toBe(true);
    expect(animating({ ...rest, transitioning: true })).toBe(true);
  });
});

describe("framePace", () => {
  it("draws at the display's pace while motion is on, whatever the last input", () => {
    expect(framePace(true, 0)).toBe(0);
    expect(framePace(true, 60_000)).toBe(0);
  });

  it("slows to one idle redraw a while after the last input when motion is off", () => {
    expect(framePace(false, 0)).toBe(0);
    expect(framePace(false, INPUT_MS - 1)).toBe(0);
    expect(framePace(false, INPUT_MS)).toBe(STILL_MS);
  });
});

describe("frameLoop with motion off", () => {
  afterEach(() => vi.useRealTimers());

  function paced(pace: { ms: number }) {
    vi.useFakeTimers();
    const s = scheduler(), drawn: number[] = [];
    const l = frameLoop({ draw: (now) => void drawn.push(now), animating: () => true, request: s.request, cancel: s.cancel, pace: () => pace.ms });
    return { s, l, drawn };
  }

  it("waits out the pace before requesting each next frame", () => {
    const { s, l, drawn } = paced({ ms: 1000 });

    l.wake();
    expect(s.requests).toBe(0);
    vi.advanceTimersByTime(999);
    expect(s.requests).toBe(0);
    vi.advanceTimersByTime(1);
    expect(s.requests).toBe(1);
    s.frame(5);
    expect(drawn).toEqual([5]);
    expect(s.requests).toBe(1);
    vi.advanceTimersByTime(1000);
    expect(s.requests).toBe(2);
    l.stop();
  });

  it("draws at once on an urgent wake, cutting a wait short", () => {
    const { s, l, drawn } = paced({ ms: 1000 });

    l.wake();
    l.wake(true);
    expect(s.requests).toBe(1);
    s.frame(7);
    expect(drawn).toEqual([7]);
    l.stop();
  });

  it("requests nothing after stop, even from a wait still running", () => {
    const { s, l } = paced({ ms: 1000 });

    l.wake();
    l.stop();
    vi.advanceTimersByTime(5000);
    expect(s.requests).toBe(0);
  });
});
