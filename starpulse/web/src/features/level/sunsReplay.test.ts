import { describe, expect, it } from "vitest";
import { goLive, movesBetween, pause, play, replayStep, scrubTo, stateAt, startReplay, type MachineEvent } from "./sunsReplay";

const ev = (at: number, machine: string, from: string, to: string): MachineEvent => ({ at, machine, event: "E", from, to });
const events = [ev(100, "build", "running", "done"), ev(200, "deliver", "idle", "ci-validate"), ev(300, "deliver", "ci-validate", "merge")];

describe("sunsReplay", () => {
  it("answers each machine's state at a time from the last event at or before it", () => {
    expect(stateAt(events, 150)).toEqual({ build: { state: "done", at: 100, from: "running" } });
    expect(stateAt(events, 250).deliver).toEqual({ state: "ci-validate", at: 200, from: "idle" });
    expect(stateAt(events, 50)).toEqual({});
    expect(stateAt(events, 300).deliver.state).toBe("merge");
  });

  it("lists the events a step crosses, so only those animate", () => {
    expect(movesBetween(events, 100, 250).map((e) => e.machine)).toEqual(["deliver"]);
    expect(movesBetween(events, 0, 100)).toHaveLength(1);
    expect(movesBetween(events, 300, 400)).toEqual([]);
  });

  it("starts live: nothing replays on load", () => {
    const s = startReplay(1000);
    expect(s).toMatchObject({ live: true, playing: false });
    expect(replayStep(s, 5, 1000)).toEqual(s);
  });

  it("scrubs into the last 24h and holds there until played", () => {
    const s = scrubTo(startReplay(100000), 90000, 100000);
    expect(s).toMatchObject({ live: false, playing: false, t: 90000 });
    expect(replayStep(s, 5, 100000)).toEqual(s);
    expect(scrubTo(s, 1, 100000).t).toBe(100000 - 24 * 3600);
    expect(scrubTo(s, 200000, 100000)).toMatchObject({ live: true });
  });

  it("plays forward, then returns to live when it reaches now", () => {
    let s = play(scrubTo(startReplay(100000), 99000, 100000));
    s = replayStep(s, 1, 100000);
    expect(s.t).toBeGreaterThan(99000);
    expect(s.live).toBe(false);
    s = replayStep(s, 1000, 100000);
    expect(s).toMatchObject({ live: true, playing: false, t: 100000 });
  });

  it("pauses, and Live returns to now from anywhere", () => {
    const s = play(scrubTo(startReplay(100000), 99000, 100000));
    expect(pause(s).playing).toBe(false);
    expect(goLive(s, 100500)).toMatchObject({ live: true, playing: false, t: 100500 });
  });
});
