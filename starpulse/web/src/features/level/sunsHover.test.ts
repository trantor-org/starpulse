import { describe, expect, it } from "vitest";
import { sunsBoard, type SunsInput } from "./sunsBoard";
import { backtrace, detailsOf, hitAt } from "./sunsHover";
import type { MachineEvent } from "./sunsReplay";

const input: SunsInput = {
  task: { id: "TASK-1", profile: "@agent-deep-high" },
  phase: "deliver",
  phases: [
    { id: "build", name: "Build", state: "done", rounds: 1, round: 1 },
    { id: "deliver", name: "Deliver", state: "ci-validate", rounds: 2, round: 2 },
    { id: "review_fix", name: "Review fix", state: "idle", rounds: 1, round: 1 },
  ],
  lenses: ["security", "ux", "ui", "code"].map((id) => ({ id, name: id, states: ["pending", "pass"], state: "pass", rounds: 1, round: 1 })),
  entries: ["Ready"],
  exits: ["Needs Attention", "Done"],
};
const board = sunsBoard(input);
const ev = (at: number, machine: string, from: string, to: string): MachineEvent => ({ at, machine, event: "E", from, to });

describe("sunsHover", () => {
  it("hits a sun, a pill and an exit by position, and nothing in the empty", () => {
    const deliver = board.suns.find((s) => s.id === "deliver")!;
    expect(hitAt(board, deliver.x + 3, deliver.y - 2)).toEqual({ kind: "sun", id: "deliver" });
    const pill = board.rows.find((r) => r.id === "deliver")!.pills[1];
    expect(hitAt(board, pill.x, pill.y)).toEqual({ kind: "pill", id: "deliver", round: 2 });
    const done = board.exits[1];
    expect(hitAt(board, done.line.x1 - 30, done.line.y)).toEqual({ kind: "exit", id: "Done" });
    expect(hitAt(board, 3, 3)).toBeNull();
  });

  it("lists a machine's moves up to a time, newest first, as its backtrace", () => {
    const events = [ev(10, "deliver", "idle", "lint"), ev(20, "build", "x", "y"), ev(30, "deliver", "lint", "ci-validate"), ev(40, "deliver", "ci-validate", "merge")];
    expect(backtrace(events, "deliver", 35).map((e) => `${e.from}>${e.to}`)).toEqual(["lint>ci-validate", "idle>lint"]);
    expect(backtrace(events, "deliver", 35, 1)).toHaveLength(1);
  });

  it("details a sun with its state and round, and an exit with what it waits for", () => {
    expect(detailsOf(board, { kind: "sun", id: "deliver" }, [])).toMatchObject({ title: "Deliver", lines: ["ci-validate", "round 2 of 2"] });
    const exit = detailsOf(board, { kind: "exit", id: "Needs Attention" }, []);
    expect(exit.title).toBe("Needs Attention");
    expect(exit.lines).toContain("the task waits on a person");
    expect(detailsOf(board, { kind: "exit", id: "Done" }, []).lines).toContain("the work is done");
  });
});
