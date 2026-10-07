// The orbit card's click focus: which body a click or Tab holds still under a ring while the replay keeps it moving.
// A second click or Enter on the focused body is held for drilling in, which waits until a user can be selected.
import type { OrbitScene } from "./orbit";
import type { Hover } from "./orbitDraw";

const same = (a: Hover | null, b: Hover | null) =>
  !!a && !!b && (a.kind === "source" ? b.kind === "source" && a.b.id === b.b.id : b.kind === "sun" && a.u.id === b.u.id);

/** The bodies Tab steps through: the sources, then each sun and end once. */
export function focusOrder(scene: OrbitScene): Hover[] {
  return [...scene.sources.map((b) => ({ kind: "source", b }) as const), ...[...new Set([...scene.suns, ...scene.ends])].map((u) => ({ kind: "sun", u }) as const)];
}

/** The focus after a still click on `hit`: the body clicked, kept on a second click, none on empty space. */
export function clickFocus(focus: Hover | null, hit: Hover | null): Hover | null {
  return same(focus, hit) ? focus : hit;
}

/** The focus after a key, and whether the card took the key: Tab past either end hands it back to the page. */
export function focusKey(order: Hover[], focus: Hover | null, key: string, shift: boolean): { focus: Hover | null; handled: boolean } {
  if (key === "Escape") return { focus: null, handled: !!focus };
  if (key === "Enter") return { focus, handled: !!focus };
  if (key !== "Tab" || !order.length) return { focus, handled: false };
  const i = order.findIndex((h) => same(h, focus)), next = i < 0 ? (shift ? order.length - 1 : 0) : i + (shift ? -1 : 1);
  return next < 0 || next >= order.length ? { focus: null, handled: false } : { focus: order[next], handled: true };
}

/** A focused or hovered body in a new snapshot's scene, or none when it is gone. */
export function refocus(scene: OrbitScene, focus: Hover | null): Hover | null {
  return focusOrder(scene).find((h) => same(h, focus)) ?? null;
}
