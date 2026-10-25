import { describe, expect, it } from "vitest";
import { drillBoard } from "./sunsDrill";
import type { MachineEvent } from "./sunsReplay";

const ev = (at: number, machine: string, from: string, to: string): MachineEvent => ({ at, machine, event: "E", from, to });
const task = { id: "TASK-1", profile: "@agent-standard-high" };

describe("drillBoard", () => {
  it("starts a task with no events at Build, one round everywhere, and nothing travelling", () => {
    const d = drillBoard(task, [], 100, 100);
    const build = d.board.suns.find((s) => s.id === "build")!;
    expect(d.board.task.at).toEqual({ x: build.x, y: build.y });
    expect(d.board.rows.every((r) => r.pills.length === 1)).toBe(true);
    expect(d.travel).toBeUndefined();
  });

  it("names each machine's state at the time shown and counts a round each time it leaves idle", () => {
    const events = [ev(10, "deliver", "idle", "lint"), ev(20, "deliver", "lint", "idle"), ev(30, "deliver", "idle", "ci-validate")];
    const row = (t: number) => drillBoard(task, events, t, t).board.rows.find((r) => r.id === "deliver")!;
    expect(row(35).state).toBe("ci-validate");
    expect(row(35).pills).toHaveLength(2);
    expect(row(15).state).toBe("lint");
    expect(row(15).pills).toHaveLength(1);
  });

  it("sits the task on the fork while any QA lens runs", () => {
    const d = drillBoard(task, [ev(10, "security", "idle", "running")], 20, 20);
    expect(d.board.task.at).toEqual({ x: d.board.dots[0].x, y: d.board.dots[0].y });
  });

  it("sends the task along the move that changes its phase between two instants, and none that stay in a phase", () => {
    const events = [ev(10, "build", "idle", "working"), ev(50, "deliver", "idle", "lint"), ev(60, "deliver", "lint", "ci-validate")];
    const hop = drillBoard(task, events, 55, 45);
    expect(hop.travel).toMatchObject({ at: 50 });
    expect(hop.travel!.to).toEqual(hop.board.task.at);
    expect(drillBoard(task, events, 65, 55).travel).toBeUndefined();
    expect(drillBoard(task, events, 45, 55).travel).toBeUndefined(); // scrubbing back never animates
  });
});
