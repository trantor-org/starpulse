// @vitest-environment jsdom
// The Star Map's colors are the chosen theme's tokens, and follow a change of theme without a reload.
import { describe, expect, it } from "vitest";
import { applyTheme } from "../features/admin/theme/apply";
import { BUILTIN, SLATE, build } from "../features/admin/theme/scheme";
import { ACT, DAG_COLOR, MACHINE, MUTED, drawing, rgba } from "./draw";
import { LEDGER_PALETTE } from "./ledgerPalette";
import { BOARD_COLOR, RAMP, tierColor, token } from "./palette";

/** Every fill a canvas call sets, in order, for the drawing primitives under test. */
function fills(draw: (d: ReturnType<typeof drawing>) => void) {
  const seen: string[] = [];
  const state: Record<string, unknown> = {};
  const cx = new Proxy(state, {
    get: (t, p: string) => (p in t ? t[p] : () => ({ width: 40 })),
    set: (t, p: string, v) => {
      if (p === "fillStyle") seen.push(String(v));
      t[p] = v;
      return true;
    },
  }) as unknown as CanvasRenderingContext2D;
  draw(drawing({ cx, K: 1, ZS: 1, clock: 0, scale: 100, hover: null }));
  return seen;
}

describe("the Star Map palette", () => {
  it("starts on the StarPulse pack and Slate, before any theme is applied", () => {
    const { t } = build(BUILTIN.starpulse, SLATE);
    expect([ACT, MUTED, DAG_COLOR.succeeded, BOARD_COLOR.done]).toEqual([t.run, t.slate, t.ok, t.ok]);
  });

  it("follows a theme applied later, in every export and in the ledger's palette", () => {
    const { t } = build(BUILTIN.nord, SLATE);
    applyTheme(t);
    expect([ACT, MUTED, MACHINE]).toEqual([t.run, t.slate, t.agent]);
    expect([DAG_COLOR.failed, DAG_COLOR.not_started, LEDGER_PALETTE.overdue]).toEqual([t.fail, t.track, t.fail]);
    expect([BOARD_COLOR.ready, BOARD_COLOR.archived, RAMP[0], RAMP[RAMP.length - 1]]).toEqual([t.ready, t.faint, t.slate, t.ok]);
    expect([tierColor("@agent-deep-high"), tierColor("@agent-standard-high"), tierColor("")]).toEqual([t["agent-text"], t.waits, t["run-text"]]);
  });

  it("draws a badge's backdrop and number from the theme's neutrals", () => {
    const { t } = build(BUILTIN.dracula ?? BUILTIN.nord, SLATE);
    applyTheme(t);
    const seen = fills((d) => d.badge({ x: 0, y: 0 }, [3], t.run));
    expect(seen).toContain(rgba(t.bg0, 0.96));
    expect(seen).toContain(t.ink);
    expect(token("ink")).toBe(t.ink);
  });
});
