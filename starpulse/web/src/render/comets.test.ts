import { describe, expect, it } from "vitest";
import { cometsAt, quantum, replayDay, DAY } from "./comets";

describe("comets", () => {
  // one arrival every half day for ten arrivals
  const at = Array.from({ length: 10 }, (_, i) => 1 + i * 0.5);

  it("leaves once per quantum of arrivals, as far along as the replay has run since the arrival that crossed it", () => {
    const span = 0.4;
    // a quantum of one: every arrival is a comet; just after the 3rd arrival (day 2) it has run a tenth of its flight
    expect(cometsAt(at, 2.04, span, 1)).toEqual([expect.closeTo(0.1, 6)]);
    expect(cometsAt(at, 2.25, span, 1)).toEqual([expect.closeTo(0.625, 6)]);
    expect(cometsAt(at, 2.45, span, 1)).toEqual([]);
  });

  it("is dark between the quantum's crossings, so a quiet edge stays dark", () => {
    // a quantum of five: only the 5th and 10th arrivals (days 3 and 5.5) send one
    const flights = [];
    for (let T = 0; T < 7; T += 0.01) if (cometsAt(at, T, 0.4, 5).length) flights.push(T);
    expect(flights.every((T) => (T >= 3 && T < 3.4) || (T >= 5.5 && T < 5.9))).toBe(true);
    expect(flights.length).toBeGreaterThan(0);
  });

  it("sends a comet for a tenth of a state's mean population, never fewer than one arrival, or for each fifth move", () => {
    expect(quantum("share", 40)).toBe(4);
    expect(quantum("share", 3)).toBe(1);
    expect(quantum("flux", 40)).toBe(4);
    expect(quantum("count", 40)).toBe(5);
  });

  it("replays a window on a loop at the level's pace, and at the live pace follows the work's own clock", () => {
    // 1 day per minute: a clock of 90 seconds is a day and a half in
    expect(replayDay("min", 90, 7, 0)).toBeCloseTo(1.5, 9);
    expect(replayDay("min", 7 * 60 + 30, 7, 0)).toBeCloseTo(0.5, 9);
    expect(replayDay("fast", 20, 7, 3)).toBeCloseTo(5, 9);
    // live never loops: it is the window's end plus the real time since the answer
    expect(replayDay("live", 3600, 7, 0)).toBeCloseTo(7 + 3600 / DAY, 9);
  });
});
