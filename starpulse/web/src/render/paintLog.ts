// A canvas 2D for the draw tests: it paints nothing and keeps every color it was asked to paint with, as the "r,g,b" of a fill or stroke
// style or a gradient stop, so a test can say which colors a drawing reached for.
export function paintLog() {
  const seen = new Set<string>(), store: Record<string, unknown> = { font: "", letterSpacing: "0px", globalAlpha: 1 };
  const note = (c: unknown) => {
    if (typeof c === "string") seen.add(rgbOf(c));
  };
  const gradient = () => ({ addColorStop: (_at: number, c: string) => note(c) });
  const cx = new Proxy(store, {
    get: (t, p: string) => {
      if (p in t) return t[p];
      if (p === "measureText") return (s: string) => ({ width: s.length * 6 });
      if (p === "createRadialGradient" || p === "createLinearGradient") return gradient;
      return () => {};
    },
    set: (t, p: string, v) => {
      if (p === "fillStyle" || p === "strokeStyle") note(v);
      t[p] = v;
      return true;
    },
  }) as unknown as CanvasRenderingContext2D;
  return { cx, seen };
}

/** A `#rrggbb` or `rgba(r,g,b,a)` as "r,g,b". */
export function rgbOf(c: string): string {
  if (c.startsWith("#")) {
    const n = parseInt(c.slice(1), 16);
    return `${n >> 16},${(n >> 8) & 255},${n & 255}`;
  }
  return c.slice(c.indexOf("(") + 1).split(",").slice(0, 3).join(",");
}
