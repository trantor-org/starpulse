// @vitest-environment jsdom
// The machine ledger's drawing takes every color from the theme tokens: with a stubbed token set applied, what it paints is that set's
// colors, and none of the colors it once hard-coded.
import { afterEach, describe, expect, it } from "vitest";
import capture from "./fixtures/events-snapshot.json";
import type { Snapshot } from "../api";
import { applyTheme } from "../features/admin/theme/apply";
import { BUILTIN, SLATE, build as buildTheme } from "../features/admin/theme/scheme";
import { drawing, type DrawCtx } from "./draw";
import { machineLedger, type LedgerIO } from "./machineLedgerDraw";
import { paintLog, rgbOf } from "./paintLog";
import { build } from "./scene";
import { merge, Moves } from "./sky";

const snap = capture as unknown as Snapshot;
const base = buildTheme(BUILTIN.starpulse, SLATE).t;
/** A token set of colors no drawing used to hard-code: every token its own, none a mix of two others. */
const stub = Object.fromEntries(
  Object.keys(base).map((k, i) => [k, "#" + [40 + ((i * 53) % 180), 40 + ((i * 97) % 180), 40 + ((i * 29) % 180)].map((n) => n.toString(16).padStart(2, "0")).join("")]),
);
/** What the ledger used to paint with before it read the tokens, as "r,g,b". */
const LEGACY = [
  "#cfd9ea", "#94a3b8", "#fbbf24", "#c084fc", "#fef3c7", "#a78bfa", "4,6,11", "6,10,20", "12,19,34",
].map((c) => (c.startsWith("#") ? rgbOf(c) : c));

function paint(flow: string, extra: (S: LedgerIO["S"]) => Partial<LedgerIO> = () => ({})) {
  const S = merge(snap), moves = new Moves(), T = snap.now ?? 0;
  moves.observe(S, T);
  const scene = build({ S, moves, W: 1920, H: 1080, T, scale: 100 }, { kind: "machine", flow });
  const { cx, seen } = paintLog();
  const dc = { cx, K: 1, ZS: 1, clock: 1, scale: 100, hover: null } as DrawCtx;
  const io: LedgerIO = {
    S, scene, FW: 1920, H: 1080, T, hotEdge: new Set<string>(), events: () => [], hhmm: () => "00:00", scrollPos: 0, pg: null, pickedRow: null,
    lpin: null, railHover: null, thumbDrag: false, glow: null, ...extra(S),
  };
  machineLedger(dc, drawing(dc), io).drawTop();
  return { seen, scene };
}

/** The ledger as it first draws, then pinned to a task of the machine (the veil) and scrolled down (the back-to-newest chip). */
const everything = () => {
  const lone = paint("build");
  const pin = (S: LedgerIO["S"]) => ({ lpin: { flow: "build", id: S!.flows.build.agents[0].id }, scrollPos: 20 });
  const pinned = paint("build", pin);
  return { lone, pinned, seen: new Set([...lone.seen, ...pinned.seen]) };
};

afterEach(() => applyTheme(base));

describe("the machine ledger's colors", () => {
  it("paints none of its old hard-coded colors under a stubbed token set", () => {
    applyTheme(stub);
    const { seen, lone } = everything();
    expect(lone.scene.top).toBeDefined();
    expect(LEGACY.filter((c) => seen.has(c))).toEqual([]);
  });

  it("paints its ink, rows and veil in the stubbed tokens", () => {
    applyTheme(stub);
    const { seen } = everything();
    const want = ["ink-2", "slate", "bg0", "surface", "agent"].map((k) => rgbOf(stub[k]));
    expect(want.filter((c) => !seen.has(c))).toEqual([]);
  });
});
