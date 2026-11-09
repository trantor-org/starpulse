// The machine ledger's scroll: the rows scroll under the fixed top by the wheel, the keys and a draggable thumb. Pure geometry in lane pixels (0 at
// the lane's top); the renderer owns the eased scroll and draws what this places.

/** The lane's height and the page's text size as a fraction (1 at 100%). */
export interface View {
  h: number;
  fs: number;
}
export interface Thumb {
  y0: number;
  y1: number;
  th: number;
  ty: number;
}
export type ScrollInput = { wheel: number; lines: boolean } | { key: string };

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
/** A wheel line, in pixels. */
const LINE = 18;
/** A thumb is never shorter than this. */
const MIN_THUMB = 24;

/** How tall the rows and the footer (when older machines remain) are together, and how far they scroll. */
export function laneContent(rows: readonly { h: number }[], foot: number, view: View): { content: number; max: number } {
  const content = rows.reduce((a, r) => a + r.h, 0) + foot;
  return { content, max: Math.max(0, content - view.h) };
}

/** Where an input aims the scroll from `goal`, kept inside `0..max`; null for a key that does not scroll. */
export function inputGoal(input: ScrollInput, goal: number, view: View, max: number): number | null {
  let to: number;
  if ("wheel" in input) to = goal + input.wheel * (input.lines ? LINE : 1);
  else if (input.key === "PageDown") to = goal + view.h * 0.9;
  else if (input.key === "PageUp") to = goal - view.h * 0.9;
  else if (input.key === "ArrowDown") to = goal + 60 * view.fs;
  else if (input.key === "ArrowUp") to = goal - 60 * view.fs;
  else if (input.key === "Home" || input.key === "0") to = 0;
  else if (input.key === "End") to = max;
  else return null;
  return clamp(to, 0, max);
}

/** The thumb's track and the thumb on it, null when nothing scrolls. */
export function thumbOf(content: number, view: View, scroll: number, max: number): Thumb | null {
  if (!max) return null;
  const y0 = 4, y1 = view.h - 6, th = Math.max(MIN_THUMB, ((y1 - y0) * view.h) / content);
  return { y0, y1, th, ty: y0 + ((y1 - y0 - th) * scroll) / max };
}

/** The scroll a drag that began at `g0` gives once the pointer has moved `dy`. */
export function dragTo(t: Thumb, g0: number, dy: number, max: number): number {
  return clamp(g0 + (dy * max) / Math.max(1, t.y1 - t.y0 - t.th), 0, max);
}

/** Where each row sits at this scroll, and which of them show: a row partly in view does. */
export function windowOf(rows: readonly { h: number }[], scroll: number, view: View): { ys: number[]; inView: number[] } {
  let y = -scroll;
  const ys = rows.map((r) => {
    const at = y;
    y += r.h;
    return at;
  });
  return { ys, inView: ys.flatMap((at, i) => (at < view.h && at + rows[i].h > 0 ? [i] : [])) };
}

/** The scroll that puts row `i` in the middle of the view. */
export function revealGoal(rows: readonly { h: number }[], i: number, view: View, max: number): number {
  const off = rows.slice(0, i).reduce((a, r) => a + r.h, 0);
  return clamp(off - (view.h - rows[i].h) / 2, 0, max);
}
