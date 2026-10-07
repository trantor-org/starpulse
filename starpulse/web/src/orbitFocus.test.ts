import { describe, expect, it } from "vitest";
import { layoutOrbit, type OrbitInput } from "./orbit";
import { clickFocus, focusKey, focusOrder, refocus } from "./orbitFocus";

function scene() {
  const t = { done: 0.7, archived: 0.3 }, w = { ready: 0.25, in_progress: 0.75 };
  const src = (id: string) => ({ id, name: id, shared: true, wip: 6, perDay: 1, cycleDays: 4, ended: { done: 7, archived: 3 }, terminalShare: t, timeShare: w });
  const input: OrbitInput = {
    suns: "terminal", terminals: [{ id: "done", role: "goal" }, { id: "archived", role: "abandoned" }], working: ["ready", "in_progress"], name: (id) => id,
    endedTotals: { done: 14, archived: 6 }, taskDays: { ready: 5, in_progress: 15 }, sources: [src("alpha"), src("beta")], aspect: 1.6,
  };
  return layoutOrbit(input);
}

describe("focusOrder", () => {
  it("lists the sources, then the suns, each once", () => {
    const s = scene(), order = focusOrder(s);
    expect(order.map((h) => (h.kind === "source" ? h.b.id : h.u.id))).toEqual(["alpha", "beta", "done", "archived"]);
  });
});

describe("clickFocus", () => {
  it("focuses the body clicked, keeps it on a second click (held for drilling), and clears on empty space", () => {
    const s = scene(), a = { kind: "source", b: s.sources[0] } as const, sun = { kind: "sun", u: s.suns[0] } as const;
    expect(clickFocus(null, a)).toBe(a);
    expect(clickFocus(a, { kind: "source", b: s.sources[0] })).toBe(a);
    expect(clickFocus(a, sun)).toBe(sun);
    expect(clickFocus(a, null)).toBeNull();
  });
});

describe("focusKey", () => {
  const s = scene(), order = focusOrder(s);

  it("Tab steps to the next body and Shift+Tab to the one before, from none to the first or the last", () => {
    expect(focusKey(order, null, "Tab", false)).toEqual({ focus: order[0], handled: true });
    expect(focusKey(order, order[0], "Tab", false)).toEqual({ focus: order[1], handled: true });
    expect(focusKey(order, null, "Tab", true)).toEqual({ focus: order[3], handled: true });
    expect(focusKey(order, order[1], "Tab", true)).toEqual({ focus: order[0], handled: true });
  });

  it("lets Tab leave the card past either end, clearing the focus", () => {
    expect(focusKey(order, order[3], "Tab", false)).toEqual({ focus: null, handled: false });
    expect(focusKey(order, order[0], "Tab", true)).toEqual({ focus: null, handled: false });
  });

  it("Esc clears a focus and leaves the key alone when there is none; Enter keeps the focus, held for drilling", () => {
    expect(focusKey(order, order[2], "Escape", false)).toEqual({ focus: null, handled: true });
    expect(focusKey(order, null, "Escape", false)).toEqual({ focus: null, handled: false });
    expect(focusKey(order, order[2], "Enter", false)).toEqual({ focus: order[2], handled: true });
    expect(focusKey(order, order[2], "a", false)).toEqual({ focus: order[2], handled: false });
  });
});

describe("refocus", () => {
  it("finds the focused body again in a new snapshot's scene, and drops it when the body is gone", () => {
    const a = scene(), b = scene();
    expect(refocus(b, { kind: "source", b: a.sources[1] })).toEqual({ kind: "source", b: b.sources[1] });
    expect(refocus(b, { kind: "sun", u: a.suns[0] })).toEqual({ kind: "sun", u: b.suns[0] });
    expect(refocus({ ...b, sources: [] }, { kind: "source", b: a.sources[1] })).toBeNull();
    expect(refocus(b, null)).toBeNull();
  });
});
