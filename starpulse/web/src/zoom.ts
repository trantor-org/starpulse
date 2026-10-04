// The canvas's view onto a level: a world point p sits on screen at p * k + (x, y).
// Each level has a fit view that frames its content box; the wheel zooms about
// the cursor between that fit and eight times it, and never below it.

export interface Point {
  x: number;
  y: number;
}
export interface View {
  k: number;
  x: number;
  y: number;
}
export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** How far past its fit a level can be zoomed. */
export const MAX_ZOOM = 8;
/** Pixels one line-mode wheel notch counts as (Firefox reports lines). */
const LINE_PX = 33;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export const toScreen = (v: View, p: Point): Point => ({ x: p.x * v.k + v.x, y: p.y * v.k + v.y });
export const toWorld = (v: View, p: Point): Point => ({ x: (p.x - v.x) / v.k, y: (p.y - v.y) / v.k });

/** The view that centres `b` in a w x h canvas at the largest scale that fits it with a margin, up to `maxK`. */
export function fitBox(b: Box, w: number, h: number, maxK = Infinity, pad = 0.94): View {
  const k = Math.min((w * pad) / (b.x1 - b.x0), (h * pad) / (b.y1 - b.y0), maxK);
  return { k, x: w / 2 - ((b.x0 + b.x1) / 2) * k, y: h / 2 - ((b.y0 + b.y1) / 2) * k };
}

/**
 * A level's default view: its content box (else the whole scene) centred in the whole canvas; an open panel floats
 * over it and never changes it. A small level is not blown up past 1.6x the scale the whole scene fits at.
 */
export function fitLevel(sc: { w: number; h: number; box?: [number, number, number, number] }, w: number, h: number): View {
  const [x0, y0, x1, y1] = sc.box ?? [0, 0, sc.w, sc.h], cap = fitBox({ x0: 0, y0: 0, x1: sc.w, y1: sc.h }, w, h).k * 1.6;
  return fitBox({ x0, y0, x1, y1 }, w, h, cap);
}

/** Whether a view is zoomed in past its level's fit. */
export const zoomedIn = (v: View | null, fit: View) => !!v && v.k > fit.k * 1.02;

/** The view once the canvas changed shape: one at the old fit takes the new fit; a zoomed-in one stays where the operator put it. */
export const refitView = (v: View, oldFit: View, newFit: View): View => (zoomedIn(v, oldFit) ? v : newFit);

/** The view after zooming by `factor` about `cursor`, or null once it reaches the fit. */
export function zoomAbout(v: View, fit: View, cursor: Point, factor: number): View | null {
  const k = clamp(v.k * factor, fit.k, fit.k * MAX_ZOOM);
  if (k <= fit.k * 1.001) return null;
  const r = k / v.k;
  return { k, x: cursor.x - (cursor.x - v.x) * r, y: cursor.y - (cursor.y - v.y) * r };
}

/** One wheel event's zoom factor, at the approved mockup's rate; a line- or page-mode delta counts as the pixels it scrolls. */
export function wheelFactor(deltaY: number, deltaMode: number, pageHeight: number): number {
  const px = deltaMode === 1 ? deltaY * LINE_PX : deltaMode === 2 ? deltaY * pageHeight : deltaY;
  return Math.exp(-px * 0.0015);
}
