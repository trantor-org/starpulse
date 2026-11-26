// @vitest-environment jsdom
// The Star Map draws a frozen task's body in the ice tint and holds it still on its orbit.
import { describe, expect, it } from "vitest";
import capture from "./fixtures/events-snapshot.json";
import type { Snapshot } from "../api";
import { boardDraw } from "./boardDraw";
import { boardTies } from "./dagTies";
import { drawing, type DrawCtx } from "./draw";
import { paintLog, rgbOf } from "./paintLog";
import { ICE } from "./palette";
import { build, orbitAngle } from "./scene";
import { merge, Moves } from "./sky";

const snap = capture as unknown as Snapshot;
const frozen = { at: "2026-11-25T20:00:00Z", by: "operator", reason: "PR 10702 merged mid-rework" };

/** The colors the tasks of the board level paint, with every task frozen or none. */
function tasksPaint(freeze: boolean) {
  const S = merge(structuredClone(snap)), moves = new Moves(), T = snap.now ?? 0;
  for (const a of S.board.agents) a.frozen = freeze ? frozen : null;
  moves.observe(S, T);
  const sc = build({ S, moves, W: 1920, H: 1080, T, scale: 100 }, { kind: "board" });
  const { cx, seen } = paintLog();
  const dc = { cx, K: 1, ZS: 1, clock: 1, scale: 100, hover: null } as DrawCtx;
  const io = {
    S, scene: sc, T, moves, liveTasks: new Set<string>(), hotEdge: new Set<string>(), events: () => [], moving: () => [], sized: (_k: string, r: number) => r,
    sourceOf: () => undefined, ties: () => boardTies(sc, S, 1), heldRows: () => [], focused: () => undefined,
  };
  boardDraw(dc, drawing(dc), io).drawTasks();
  return { seen, tasks: sc.tasks.length };
}

describe("a frozen task on the Star Map", () => {
  it("draws its body in the ice tint, which an unfrozen board never uses", () => {
    const warm = tasksPaint(false), cold = tasksPaint(true);

    expect(cold.tasks).toBeGreaterThan(0);
    expect(cold.seen.has(rgbOf(ICE))).toBe(true);
    expect(warm.seen.has(rgbOf(ICE))).toBe(false);
  });

  it("holds still on its slot while an unfrozen one moves on its orbit", () => {
    const body = { a0: 1, w: 0.5 };

    expect(orbitAngle({ ...body, frozen }, 10)).toBe(1);
    expect(orbitAngle(body, 10)).toBe(6);
    expect(orbitAngle({ ...body, frozen: null }, 10)).toBe(6);
  });
});
