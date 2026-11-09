// @vitest-environment jsdom
// The Board's drawing takes every color from the theme tokens: with a stubbed token set applied, what it paints is that set's colors, and
// none of the colors it once hard-coded.
import { afterEach, describe, expect, it } from "vitest";
import capture from "./fixtures/events-snapshot.json";
import type { Snapshot } from "../api";
import { applyTheme } from "../features/admin/theme/apply";
import { BUILTIN, SLATE, build as buildTheme } from "../features/admin/theme/scheme";
import { boardDraw, orbiterLook } from "./boardDraw";
import { boardTies } from "./dagTies";
import { drawing, type DrawCtx } from "./draw";
import { paintLog, rgbOf } from "./paintLog";
import { MUTED } from "./palette";
import { build, type Scene } from "./scene";
import { merge, Moves } from "./sky";

const snap = capture as unknown as Snapshot;
const base = buildTheme(BUILTIN.starpulse, SLATE).t;
/** A token set of colors no drawing used to hard-code: every token its own, none a mix of two others. */
const stub = Object.fromEntries(
  Object.keys(base).map((k, i) => [k, "#" + [40 + ((i * 53) % 180), 40 + ((i * 97) % 180), 40 + ((i * 29) % 180)].map((n) => n.toString(16).padStart(2, "0")).join("")]),
);
/** What the Board used to paint with before it read the tokens, as "r,g,b". */
const LEGACY = [
  "#94a3b8", "#c084fc", "#d8c8f5", "#5eead4", "#a78bfa", "#cfd9ea", "#f5f3ff", "#c4b5fd", "#e879f9", "#dbe4f3", "6,10,20", "10,14,26",
].map((c) => (c.startsWith("#") ? rgbOf(c) : c));

function paint(level: Parameters<typeof build>[1], pick: (sc: Scene) => unknown = () => null) {
  const S = merge(snap), moves = new Moves(), T = snap.now ?? 0;
  moves.observe(S, T);
  const sc = build({ S, moves, W: 1920, H: 1080, T, scale: 100 }, level);
  const { cx, seen } = paintLog(), hover = pick(sc);
  const dc = { cx, K: 1, ZS: 1, clock: 1, scale: 100, hover } as DrawCtx;
  const io = {
    S, scene: sc, T, moves, liveTasks: new Set<string>(), hotEdge: new Set<string>(), events: () => [], moving: () => [], sized: (_k: string, r: number) => r,
    sourceOf: () => undefined, ties: () => boardTies(sc, S, 1), heldRows: () => [], focused: () => undefined,
  };
  const b = boardDraw(dc, drawing(dc), io);
  b.drawGalaxies();
  b.drawMoons();
  b.drawBoardEdges();
  b.drawTies();
  b.drawStateLinks();
  b.drawSun();
  b.drawPlanets();
  b.drawTasks();
  b.drawMachineEdges(sc.mEdges);
  b.drawStates(sc.mStates, true);
  b.drawMachineTasks();
  b.drawStars();
  return seen;
}

/** Every color the Board, a sun's level, and the levels with tasks and machines paint. */
const everything = () => new Set(["new", "in_progress", "review"].flatMap((id) => [...paint({ kind: "state", id })]).concat([...paint({ kind: "board" })]));

afterEach(() => applyTheme(base));

describe("the Board's drawing", () => {
  it("paints none of its old hard-coded colors under a stubbed token set", () => {
    applyTheme(stub);
    const seen = everything();
    expect(seen.size).toBeGreaterThan(5);
    for (const c of LEGACY) expect(seen.has(c), c).toBe(false);
  });

  it("paints a hangar's name and a sun's core in the stubbed tokens", () => {
    applyTheme(stub);
    const seen = everything();
    expect(seen.has(rgbOf(stub["agent-hi"]))).toBe(true); // a sun's pale core
    expect(seen.has(rgbOf(stub["ink-2"]))).toBe(true); // a hangar's and a label's ink
  });

  it("draws an unfinished or unknown DAG run in the muted role", () => {
    applyTheme(stub);
    expect(MUTED).toBe(stub.slate);
    expect([orbiterLook("queued").color, orbiterLook("nope").color]).toEqual([stub.slate, stub.slate]);
  });
});
