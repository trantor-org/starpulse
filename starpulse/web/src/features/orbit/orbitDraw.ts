// Draws the orbit card from the approved hub mockup (Mock C), quietened: at rest only the suns, each source a planet on its closed
// orbit with a short tail, their names, and comets replayed from real arrivals move or show; a hover adds the shares, the share ring
// and the traces. Canvas only: no DOM, no state beyond what the caller hands it, so a frame is a pure function of the `Frame`.
import { cometsAt, FLIGHT_S, paceS, quantum, replayDay, type Measure, type Pace } from "../../render/comets";
import { positionAt, separateLabels, type OrbitBody, type OrbitInput, type OrbitScene, type Sun } from "./orbit";
import { TAU } from "../../render/scene";

export type Hover = { kind: "source"; b: OrbitBody } | { kind: "sun"; u: Sun };

export interface Frame {
  scene: OrbitScene;
  input: OrbitInput;
  /** Screen pixels per world unit, and how far the view is zoomed past its fit. */
  k: number;
  zs: number;
  /** Animation seconds. */
  clock: number;
  hover: Hover | null;
  /** The body a click or Tab holds: ringed wherever it has moved to, and lit like a hover while the pointer is elsewhere. */
  focus?: Hover | null;
  measure: Measure;
  pace: Pace;
  /** Days in the window the comets replay. */
  days: number;
  /** Arrivals by source, then sun, as days from the window's start. */
  arrivals: Record<string, Record<string, number[]>>;
  /** Each source label's eased vertical offset, kept between frames by the caller. */
  offsets: Map<string, number>;
}

const DAY = 86400;
const PACE_LABEL: Record<Pace, string> = { live: "live", min: "1 day / min", fast: "1 day / 10 s" };
/** Segments in the tail behind a planet, each a six-hundredth of its period. */
export const TAIL = 20;

/** The arrivals as days from the window's start, by source and sun, oldest first. */
export function arrivalDays(arrivals: { source: string; state: string; at: number }[], now: number, windowS: number): Frame["arrivals"] {
  const out: Frame["arrivals"] = {};
  for (const a of arrivals) ((out[a.source] ??= {})[a.state] ??= []).push((a.at - (now - windowS)) / DAY);
  for (const by of Object.values(out)) for (const at of Object.values(by)) at.sort((x, y) => x - y);
  return out;
}

/** The working state a source's runs spend most of their time in, named in its hover tip. */
export function bottleneck(b: Pick<OrbitBody, "src">): string | null {
  const top = Object.entries(b.src.timeShare).sort((x, y) => y[1] - x[1])[0];
  return top ? top[0] : null;
}

/** The sun or source under a world point, suns first, within 14 units of the body. */
export function hitOrbit(scene: OrbitScene, x: number, y: number): Hover | null {
  for (const u of new Set([...scene.suns, ...scene.ends])) if (Math.hypot(u.x - x, u.y - y) < u.r + 14) return { kind: "sun", u };
  for (const b of scene.sources) if (Math.hypot(b.x - x, b.y - y) < b.r + 14) return { kind: "source", b };
  return null;
}

const rgba = (h: string, a: number) => {
  const n = parseInt(h.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
};
const ease = (u: number) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
type P = { x: number; y: number };
const bez = (a: P, c: P, b: P, t: number): P => ({ x: (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * c.x + t * t * b.x, y: (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * c.y + t * t * b.y });

type Cx = CanvasRenderingContext2D;
function text(cx: Cx, s: string, x: number, y: number, size: number, col: string, align: CanvasTextAlign = "center", weight = 400) {
  cx.font = `${weight} ${size}px Inter, system-ui, sans-serif`;
  cx.fillStyle = col;
  cx.textAlign = align;
  cx.textBaseline = "middle";
  cx.fillText(s, x, y);
}
function circle(cx: Cx, x: number, y: number, r: number, stroke: string, w = 1, dash?: number[] | null) {
  cx.strokeStyle = stroke;
  cx.lineWidth = w;
  cx.setLineDash(dash ?? []);
  cx.beginPath();
  cx.arc(x, y, r, 0, TAU);
  cx.stroke();
  cx.setLineDash([]);
}
/** The steady ring round the focused body, solid so it reads apart from a dashed body's own edge. */
function focusRing(cx: Cx, x: number, y: number, r: number, zs: number) {
  cx.strokeStyle = rgba("#e2e8f0", 0.85);
  cx.lineWidth = 1.5 / Math.max(1, zs);
  cx.beginPath();
  cx.arc(x, y, r, 0, TAU);
  cx.stroke();
}
function dot(cx: Cx, x: number, y: number, r: number, fill: string) {
  cx.fillStyle = fill;
  cx.beginPath();
  cx.arc(x, y, r, 0, TAU);
  cx.fill();
}
function disc(cx: Cx, x: number, y: number, r: number, col: string, hot: boolean, dashed: boolean, alpha: number) {
  const g = cx.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, rgba(col, alpha));
  g.addColorStop(1, rgba(col, 0.02));
  cx.fillStyle = g;
  cx.beginPath();
  cx.arc(x, y, r, 0, TAU);
  cx.fill();
  circle(cx, x, y, r, rgba(col, hot ? 0.9 : 0.4), hot ? 2 : 1.2, dashed ? [4, 5] : null);
}

/** A body's name, a fixed size on screen: readable at fit, never ballooning when zoomed in. */
function label(cx: Cx, k: number, name: string, x: number, y: number, size: number, bright = true) {
  cx.letterSpacing = `${0.6 / k}px`;
  text(cx, name, x, y, size / k, rgba("#cfd9ea", bright ? 0.95 : 0.58), "center", 300);
  cx.letterSpacing = "0px";
}

/** Where a sun's label stands: under a lone sun, else outward from the centre. */
function sunLabel(scene: OrbitScene, u: Sun, k: number): { x: number; y: number } {
  const out = Math.atan2(u.y - scene.c.y, u.x - scene.c.x);
  return scene.suns.length === 1 ? { x: u.x, y: u.y + u.r + 26 / k } : { x: u.x + Math.cos(out) * (u.r + 70), y: u.y + Math.sin(out) * (u.r + 50) + 6 / k };
}

function comet(cx: Cx, zs: number, p0: P, c: P, p1: P, u: number, r: number, col: string) {
  const n = 14, span = 0.27 * Math.min(1, u + 0.05);
  for (let i = 1; i <= n; i++) {
    const a = bez(p0, c, p1, Math.max(0, u - span * (1 - (i - 1) / n))), b = bez(p0, c, p1, Math.max(0, u - span * (1 - i / n)));
    cx.strokeStyle = rgba(col, (i / n) * 0.6);
    cx.lineWidth = ((i / n) * 2.6) / Math.max(1, zs * 0.8);
    cx.beginPath();
    cx.moveTo(a.x, a.y);
    cx.lineTo(b.x, b.y);
    cx.stroke();
  }
  const h = bez(p0, c, p1, u), gr = 14 / zs;
  cx.globalCompositeOperation = "lighter";
  const g = cx.createRadialGradient(h.x, h.y, 0, h.x, h.y, gr);
  g.addColorStop(0, rgba(col, 0.7));
  g.addColorStop(1, rgba(col, 0));
  cx.fillStyle = g;
  cx.beginPath();
  cx.arc(h.x, h.y, gr, 0, TAU);
  cx.fill();
  cx.globalCompositeOperation = "source-over";
  dot(cx, h.x, h.y, r, rgba(col, 0.95));
}

const pct = (x: number | undefined) => Math.round((x ?? 0) * 100);

/** One frame of the orbit card in world coordinates: the caller has set the view's transform. */
export function drawOrbit(cx: Cx, f: Frame) {
  const { scene, k, zs, clock } = f, work = scene.ends !== scene.suns, lit = f.hover ?? f.focus ?? null;
  const focus = lit?.kind === "source" ? lit.b : null, fsun = lit?.kind === "sun" ? lit.u : null;
  const ringed = f.focus?.kind === "source" ? f.focus.b : f.focus?.u;
  const T = replayDay(f.pace, clock, f.days, 0), span = FLIGHT_S / paceS(f.pace);
  // the suns, and in working mode the terminal column beside them
  for (const u of work ? [...scene.suns, ...scene.ends] : scene.suns) {
    const end = !scene.suns.includes(u), hot = fsun === u;
    disc(cx, u.x, u.y, u.r, u.col, hot, u.role !== "goal", 0.4);
    if (ringed === u) focusRing(cx, u.x, u.y, u.r + 8, zs);
    // a body's numbers are in its hover tip; the canvas names it
    const at = end ? { x: u.x, y: u.y + u.r + 26 / k } : sunLabel(scene, u, k);
    label(cx, k, u.name, at.x, at.y, 13);
  }

  // each source's position, so the labels can be separated before they are drawn
  for (const b of scene.sources) {
    const q = positionAt(scene, b, (((clock / b.period + b.phase) % 1) + 1) % 1);
    b.x = q.x;
    b.y = q.y;
  }
  // a label is its name and the share line under it; the suns' labels stand still and the sources' keep clear of them and of each other
  const fixed = scene.suns.map((u) => {
    const at = sunLabel(scene, u, k);
    return { x: at.x, y: at.y + 7.5 / k, w: (27 * 13 * 0.5 + 6) / k, h: 30 / k };
  });
  const rects = [...fixed, ...scene.sources.map((b) => ({ x: b.x, y: b.y + b.r + 37.5 / k, w: (Math.max(b.name.length, 9) * 12.5 * 0.56 + 6) / k, h: 34 / k }))];
  const want = separateLabels(rects).slice(fixed.length);
  scene.sources.forEach((b, i) => {
    const had = f.offsets.get(b.id) ?? want[i];
    f.offsets.set(b.id, had + (want[i] - had) * 0.4);
  });

  for (const b of scene.sources) {
    const hot = focus === b, dim = (focus && !hot) || fsun, u = (((clock / b.period + b.phase) % 1) + 1) % 1;
    // the closed orbit, faint, with a short tail fading behind the planet
    const path = b.path, n = path.length / 2;
    cx.strokeStyle = rgba(b.col, hot ? 0.4 : dim ? 0.05 : 0.16);
    cx.lineWidth = (hot ? 1.6 : 1) / Math.max(1, zs);
    cx.beginPath();
    cx.moveTo(path[0], path[1]);
    for (let i = 1; i < n; i++) cx.lineTo(path[2 * i], path[2 * i + 1]);
    cx.stroke();
    for (let j = 1; j <= TAIL; j++) {
      const p0 = positionAt(scene, b, (u - j / 600 + 1) % 1), p1 = positionAt(scene, b, (u - (j - 1) / 600 + 1) % 1);
      cx.strokeStyle = rgba(b.col, (1 - j / TAIL) * (dim ? 0.12 : 0.5));
      cx.lineWidth = 2 / Math.max(1, zs);
      cx.beginPath();
      cx.moveTo(p0.x, p0.y);
      cx.lineTo(p1.x, p1.y);
      cx.stroke();
    }
    // a hovered source, or a hovered sun, traces each share it has there
    if (hot || fsun)
      for (const sn of scene.suns) {
        const p = b.w[sn.id];
        if (!p || (fsun && fsun !== sn)) continue;
        const g = cx.createLinearGradient(b.x, b.y, sn.x, sn.y);
        g.addColorStop(0, rgba(b.col, 0.6));
        g.addColorStop(1, rgba(sn.col, 0.6));
        cx.strokeStyle = g;
        cx.setLineDash([2, 5].map((d) => (d / k) * 1.2));
        cx.lineDashOffset = ((-clock * 12) / k) * 1.2;
        cx.lineWidth = (0.6 + 3 * p) / Math.max(1, zs);
        cx.beginPath();
        cx.moveTo(b.x, b.y);
        cx.lineTo(sn.x, sn.y);
        cx.stroke();
        cx.setLineDash([]);
      }
    disc(cx, b.x, b.y, b.r, b.col, hot, !b.src.shared, 0.32);
    dot(cx, b.x, b.y, 3.5, rgba(b.col, 0.95));
    // the ring round a hovered planet: its runs' ends, an arc for each
    let a0 = -Math.PI / 2;
    if (hot) for (const sn of scene.ends) {
      const sp = (b.src.terminalShare[sn.id] ?? 0) * TAU;
      if (!sp) continue;
      cx.strokeStyle = rgba(sn.col, 0.9);
      cx.lineWidth = 2.6 / Math.max(1, zs);
      cx.beginPath();
      cx.arc(b.x, b.y, b.r + 6, a0 + 0.04, a0 + sp - 0.04);
      cx.stroke();
      a0 += sp;
    }
    if (ringed === b) focusRing(cx, b.x, b.y, b.r + 12, zs);
    const ly = b.y + b.r + 30 / k + (f.offsets.get(b.id) ?? 0);
    label(cx, k, b.name, b.x, ly, 12.5, hot);

    // activity: a comet falls from the planet into a sun each time that source's arrivals there cross the quantum
    if (!focus || hot)
      for (const sn of scene.ends) {
        if (fsun && fsun !== sn && scene.ends.includes(fsun)) continue;
        const dx = sn.x - b.x, dy = sn.y - b.y, L = Math.hypot(dx, dy) || 1, p0 = { x: b.x, y: b.y }, p1 = { x: sn.x - (dx / L) * sn.r, y: sn.y - (dy / L) * sn.r };
        const c = { x: (p0.x + p1.x) / 2 - dy * 0.15, y: (p0.y + p1.y) / 2 + dx * 0.15 };
        for (const v of cometsAt(f.arrivals[b.id]?.[sn.id] ?? [], T, span, quantum(f.measure, b.src.wip))) comet(cx, zs, p0, c, p1, ease(v), 2.6, sn.role === "goal" ? b.col : sn.col);
      }
  }
  text(cx, `replay · day ${Math.floor(T) + 1} of ${f.days} · ${PACE_LABEL[f.pace]}`, scene.c.x - 110 / k, scene.box[3] + 62 / k, 11 / k, rgba("#fbbf24", 0.7), "left", 500);
}

/** What the hover tip says of a sun or a source: its kind, name, facts, and the share each other body has of it. */
export function describeHover(h: Hover, f: Pick<Frame, "scene" | "input" | "days">): { kind: string; name: string; lines: string[]; chips: { col: string; text: string }[] } {
  const { scene, input, days } = f, goal = scene.ends.find((e) => e.role === "goal") ?? scene.ends[0];
  if (h.kind === "sun") {
    const u = h.u, working = !scene.ends.includes(u);
    return {
      kind: working ? "working state" : `terminal · ${u.role}`,
      name: u.name,
      lines: [working ? `${Math.round(u.n)} task-days spent here in ${days} days` : `${u.n} runs ended here in ${days} days`],
      chips: scene.sources.map((b) => ({ col: b.col, text: working ? `${b.name} ${pct(b.src.timeShare[u.id])}% of its time` : `${b.name} ${b.src.ended[u.id] ?? 0}` })),
    };
  }
  const b = h.b, ended = Object.values(b.src.ended).reduce((a, n) => a + n, 0), neck = bottleneck(b);
  return {
    kind: b.src.shared ? "source" : "source · unattributed",
    name: b.name,
    lines: [
      `${ended} runs ended · ${b.src.wip} open · ${pct(b.src.terminalShare[goal.id])}% reached ${goal.name} · ${Math.round(b.src.cycleDays * 10) / 10}d in work per run`,
      ...(neck ? [`bottleneck: ${input.name(neck)}`] : []),
    ],
    chips: scene.suns.filter((u) => (b.w[u.id] ?? 0) >= 0.005).map((u) => ({ col: u.col, text: `${u.name} ${pct(b.w[u.id])}%` })),
  };
}
