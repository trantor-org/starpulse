import { describe, expect, it } from "vitest";
import { layoutOrbit } from "./orbit";
import { orbitInput, type LevelResponse } from "./levelData";
import { duration, focusDetails } from "./orbitDetails";

const DAY = 86400, NOW = 1e9;
const level = (suns: "terminal" | "working" = "terminal"): LevelResponse => ({
  now: NOW, window_s: 7 * DAY, history_s: 30 * DAY, machine: "task", goal: "done",
  level: {
    title: "Runs", subject: "task", runs: "runs", gates: [], terminals: [{ id: "done", role: "goal" }, { id: "archived", role: "abandoned" }],
    orbit: { suns, working: ["ready", "in_progress"] }, facets: [], activity: { measure: "share", pace: "live" },
  },
  wip: { count: 3, states: { in_progress: 2, ready: 1 } },
  throughput: { count: 14, per_day: 2 },
  time_in_state: [{ id: "ready", visits: 4, task_s: 2 * DAY, mean_s: DAY / 2 }, { id: "in_progress", visits: 5, task_s: 5 * DAY, mean_s: DAY }],
  aging: {
    threshold_s: 3 * DAY,
    runs: [
      { source: "a", task: "T-1", state: "in_progress", age_s: 4 * DAY, over: true },
      { source: "a", task: "T-2", state: "ready", age_s: 2 * 3600, over: false },
      { source: "unattributed", task: "T-3", state: "in_progress", age_s: DAY, over: false },
    ],
  },
  orbit: { suns, terminals: { done: { ended: 14 }, archived: { ended: 6 } }, working: { ready: { task_s: 2 * DAY }, in_progress: { task_s: 5 * DAY } } },
  arrivals: [
    { source: "a", state: "archived", at: NOW - 3 * DAY },
    { source: "unattributed", state: "done", at: NOW - 2 * DAY },
    { source: "a", state: "done", at: NOW - 3 * 3600 },
  ],
  sources: [
    {
      id: "a", shared: true, wip: 2, ended: { done: 10, archived: 4 }, terminal_share: { done: 10 / 14, archived: 4 / 14 },
      dwell: { ready: { visits: 3, task_s: 2 * DAY, mean_s: 2 * DAY / 3 }, in_progress: { visits: 2, task_s: 5 * DAY, mean_s: 2.5 * DAY } },
      time_share: { ready: 2 / 7, in_progress: 5 / 7 }, drift: { added: ["triage"], removed: ["waiting"] },
    },
    { id: "unattributed", shared: false, wip: 1, ended: { done: 4, archived: 2 }, terminal_share: { done: 4 / 6, archived: 2 / 6 }, dwell: {}, time_share: {} },
  ],
});
const name = (id: string) => id.toUpperCase();
const setup = (suns: "terminal" | "working" = "terminal") => {
  const l = level(suns), scene = layoutOrbit(orbitInput(l, name, 1.6));
  return { l, scene };
};

describe("duration", () => {
  it("reads in minutes under an hour, hours under a day, else days, to one place", () => {
    expect([duration(600), duration(2 * 3600), duration(1.5 * 3600), duration(2.5 * DAY), duration(4 * DAY)]).toEqual(["10m", "2h", "1.5h", "2.5d", "4d"]);
  });
});

describe("focusDetails", () => {
  it("gives a source its open and ended runs, each end's count and share, and its drift", () => {
    const { l, scene } = setup(), d = focusDetails({ kind: "source", b: scene.sources.find((b) => b.id === "a")! }, l, scene, name);
    expect(d.kind).toBe("source");
    expect(d.facts).toEqual([["Open now", "2"], ["Ended", "14 in 7 days"], ["DONE", "10 · 71%"], ["ARCHIVED", "4 · 29%"], ["Drift", "+triage −waiting"]]);
  });

  it("lists a source's time in each state, its open runs oldest first with the aging flag, and its latest arrivals newest first", () => {
    const { l, scene } = setup(), d = focusDetails({ kind: "source", b: scene.sources.find((b) => b.id === "a")! }, l, scene, name);
    const s = Object.fromEntries(d.sections.map((x) => [x.title, x.rows]));
    expect(s["Time in each state"].map((r) => [r.label, r.value])).toEqual([["IN_PROGRESS", "71% · 2 stays · mean 2.5d"], ["READY", "29% · 3 stays · mean 16h"]]);
    expect(s["Open runs, oldest first"].map((r) => [r.label, r.value, !!r.warn])).toEqual([["T-1", "IN_PROGRESS · 4d", true], ["T-2", "READY · 2h", false]]);
    expect(s["Latest arrivals"].map((r) => [r.label, r.value])).toEqual([["DONE", "3h ago"], ["ARCHIVED", "3d ago"]]);
  });

  it("leaves out a section with nothing in it", () => {
    const { l, scene } = setup(), d = focusDetails({ kind: "source", b: scene.sources.find((b) => b.id === "unattributed")! }, l, scene, name);
    expect(d.kind).toBe("source · unattributed");
    expect(d.sections.map((x) => x.title)).toEqual(["Open runs, oldest first", "Latest arrivals"]);
  });

  it("gives a terminal sun its runs, its share of every end, its last day, each source's count and its latest arrivals", () => {
    const { l, scene } = setup(), done = scene.suns.find((u) => u.id === "done")!, d = focusDetails({ kind: "sun", u: done }, l, scene, name);
    expect(d.kind).toBe("terminal · goal");
    expect(d.facts).toEqual([["Ended here", "14 in 7 days"], ["Share of all ended", "70%"], ["Last 24 hours", "1"]]);
    const s = Object.fromEntries(d.sections.map((x) => [x.title, x.rows]));
    expect(s["By source"].map((r) => [r.label, r.value])).toEqual([["a", "10 · 71%"], ["unattributed", "4 · 29%"]]);
    expect(s["Latest arrivals"].map((r) => [r.label, r.value])).toEqual([["a", "3h ago"], ["unattributed", "2d ago"]]);
  });

  it("gives a working sun its open runs, its stays and each source's time there", () => {
    const { l, scene } = setup("working"), u = scene.suns.find((x) => x.id === "in_progress")!, d = focusDetails({ kind: "sun", u }, l, scene, name);
    expect(d.kind).toBe("working state");
    expect(d.facts).toEqual([["Open now", "2"], ["Task-days", "5 in 7 days"], ["Stays", "5 · mean 1d"]]);
    const s = Object.fromEntries(d.sections.map((x) => [x.title, x.rows]));
    expect(s["By source"].map((r) => [r.label, r.value])).toEqual([["a", "71% of its time · mean 2.5d"]]);
    expect(s["Open runs here, oldest first"].map((r) => [r.label, r.value, !!r.warn])).toEqual([["T-1", "a · 4d", true], ["T-3", "unattributed · 1d", false]]);
  });

  it("shows five rows of a long list and counts the rest", () => {
    const l = level(), runs = Array.from({ length: 8 }, (_, i) => ({ source: "a", task: `T-${i}`, state: "ready", age_s: (8 - i) * DAY, over: false }));
    l.aging.runs = runs;
    const scene = layoutOrbit(orbitInput(l, name, 1.6)), d = focusDetails({ kind: "source", b: scene.sources.find((b) => b.id === "a")! }, l, scene, name);
    const open = d.sections.find((x) => x.title === "Open runs, oldest first")!;
    expect(open.rows.map((r) => r.label)).toEqual(["T-0", "T-1", "T-2", "T-3", "T-4"]);
    expect(open.more).toBe(3);
  });
});
