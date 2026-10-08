import { describe, expect, it } from "vitest";
import type { KanbanTask } from "./kanban";
import { age, leaderboard } from "./leaderboard";

const NOW = 1_000_000;
const task = (id: string, lane: string, workableSince: number | null): KanbanTask => ({
  id, title: `title of ${id}`, lane, milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, machines: [], workableSince,
});
const ago = (seconds: number) => NOW - seconds;

describe("leaderboard", () => {
  it("leaves out tasks that are not workable", () => {
    const groups = leaderboard([task("TASK-1", "ready", ago(600)), task("TASK-2", "ready", null)], NOW);
    expect(groups.map((g) => g.rows.map((r) => r.id))).toEqual([["TASK-1"]]);
  });

  it("groups by status in the approved order and leaves a status with no workable task out", () => {
    const groups = leaderboard([
      task("TASK-1", "ready", ago(60)), task("TASK-2", "waiting", ago(60)), task("TASK-3", "review", ago(60)),
      task("TASK-4", "in_progress", ago(60)), task("TASK-5", "needs_attention", ago(60)), task("TASK-6", "done", ago(60)), task("TASK-7", "new", null),
    ], NOW);
    expect(groups.map((g) => [g.status, g.label])).toEqual([
      ["needs_attention", "Needs you"], ["in_progress", "Working"], ["review", "Review"], ["waiting", "Waiting"], ["ready", "Ready"],
    ]);
    expect(leaderboard([task("TASK-1", "ready", null), task("TASK-2", "done", ago(60))], NOW)).toEqual([]);
  });

  it("keeps the three tasks workable longest in each status, breaking a tie by task number", () => {
    const groups = leaderboard([
      task("TASK-9", "ready", ago(100)), task("TASK-10", "ready", ago(500)), task("TASK-2", "ready", ago(500)),
      task("TASK-3", "ready", ago(300)), task("TASK-4", "review", ago(10)),
    ], NOW);
    expect(groups.map((g) => g.rows.map((r) => r.id))).toEqual([["TASK-4"], ["TASK-2", "TASK-10", "TASK-3"]]);
  });

  it("counts each status's workable tasks and the open ones held back", () => {
    const [ready] = leaderboard([
      task("TASK-1", "ready", ago(10)), task("TASK-2", "ready", ago(20)), task("TASK-3", "ready", ago(30)), task("TASK-4", "ready", ago(40)),
      task("TASK-5", "ready", null), task("TASK-6", "ready", null),
    ], NOW);
    expect([ready.workable, ready.held, ready.rows.length]).toEqual([4, 2, 3]);
  });

  it("sizes every bar against the longest age shown, never under 2%", () => {
    const groups = leaderboard([task("TASK-1", "ready", ago(1000)), task("TASK-2", "review", ago(500)), task("TASK-3", "review", ago(1))], NOW);
    expect(groups.flatMap((g) => g.rows.map((r) => [r.id, r.width]))).toEqual([["TASK-2", 50], ["TASK-3", 2], ["TASK-1", 100]]);
  });

  it("writes an age as minutes under an hour, hours under a day, else days", () => {
    expect([0, 59, 60, 3599, 3600, 86399, 86400, 3 * 86400].map(age)).toEqual(["1m", "1m", "1m", "59m", "1h", "23h", "1d", "3d"]);
  });
});
