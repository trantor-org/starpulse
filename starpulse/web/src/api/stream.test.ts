import { describe, expect, it } from "vitest";
import { foldRows } from "./stream";
import type { LedgerRow } from ".";

describe("foldRows", () => {
  const row = (key: string, at: number, pinned = false): LedgerRow => ({ key, at, tasks: [key], runs: {}, fails: {}, pinned });
  const [a, b, c] = [row("a", 30), row("b", 20), row("c", 10)];

  it("replaces the changed row and keeps every other row's reference", () => {
    const b2 = row("b", 20, true);

    const next = foldRows([a, b, c], [b2]);

    expect(next).toEqual([a, b2, c]);
    expect([next[0], next[2]]).toEqual([a, c]);
    expect(next[0]).toBe(a);
    expect(next[1]).toBe(b2);
  });

  it("places a new row by its time among the held ones, newest first", () => {
    const next = foldRows([a, c], [row("n", 40), row("m", 20)]);

    expect(next.map((r) => r.key)).toEqual(["n", "a", "m", "c"]);
    expect(next[1]).toBe(a);
  });
});

describe("the page's sources", () => {
  const sources = import.meta.glob<string>(["../**/*.ts", "../**/*.tsx", "!../**/*.test.ts", "!../**/*.test.tsx", "!../api/types.gen.ts"], { query: "?raw", import: "default", eager: true });

  it("name no snapshot endpoint and keep no timed poll of one: every flow arrives over the stream", () => {
    const polling = Object.entries(sources).filter(([, text]) => /api\/snapshot|fetchSnapshot|\bpoll/i.test(text));

    expect(Object.keys(sources).length).toBeGreaterThan(5);
    expect(polling.map(([file]) => file)).toEqual([]);
  });

  it("keeps no timed GET refresh for level", () => {
    // clock-only setInterval (ago stamps) may share a file with apiFetch; ban the live-data refresh patterns
    const text = Object.entries(sources)
      .filter(([file]) => /orbit\/levelData/.test(file))
      .map(([, body]) => body)
      .join("\n");
    expect(text).not.toMatch(/setInterval/);
    expect(text).not.toMatch(/REFRESH_MS/);
  });

  it("keeps no timed refresh anywhere but the clock-only and non-data timers", () => {
    // each allowed timer repaints a clock stamp, a DOM busy state or a simulator (the drill-in's replay and move animation); none refetches live data
    const clockOnly = /\/(App\.tsx|Kanban\.tsx|Dags\.tsx|SunsDrillIn\.tsx|reload\.ts|renderer\.ts)$/;
    const timed = Object.entries(sources)
      .filter(([file, text]) => !clockOnly.test(file) && /setInterval|REFRESH_MS/.test(text))
      .map(([file]) => file);
    const refreshing = Object.entries(sources)
      .filter(([, text]) => /REFRESH_MS/.test(text))
      .map(([file]) => file);
    const idle = Object.entries(sources)
      .filter(([file, text]) => clockOnly.test(file) && !/setInterval/.test(text))
      .map(([file]) => file);

    expect(timed).toEqual([]);
    expect(refreshing).toEqual([]);
    // an allowlisted file that no longer holds a timer is a stale entry: drop it from the list
    expect(idle).toEqual([]);
  });
});
