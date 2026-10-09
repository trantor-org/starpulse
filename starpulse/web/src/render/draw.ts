// The canvas drawing primitives every level shares: text, names, rings, discs, black holes, comets, pulses, flow lines, arrows and
// badges. `drawing(dc)` binds them to a canvas and the zoom, scale and clock of the frame being drawn; the renderer and the machine
// ledger's drawing (machineLedgerDraw.ts) take the same set, so the two draw in one hand.
import type { ContractReport, LedgerRow, RawAgent } from "../api";
import { labelPx } from "../features/admin/adminPrefs";
import type { Hub, Orbiter } from "./dagTies";
import {
  TAU, bez, terminal, textW,
  type BEdge, type Body, type Galaxy, type GNode, type Hop, type LedgerView, type MachineTask, type MEdge, type Moon, type MState, type Planet, type Pt, type RowView, type Star, type SubState, type Sun,
} from "./scene";

/** Activity: everything that moves on any level uses this one colour. */
export const ACT = "#fbbf24";
/** The colour of a traced path, and of the cue for a hop with no line. */
export const TRACE = "#fbbf24", OFF = "#fb7185";
/** A mapped machine (machine.source: a third party moves it) is drawn like a local one, in a colour of its own: blue, never purple. */
export const EXT = "#60a5fa";
/** An agent is coloured by the tier its profile names (`@agent-<tier>-<effort>`); a person or fast is the other colour. */
export const tierColor = (profile = "") =>
  profile.startsWith("@agent-deep") ? "#c4b5fd" : profile.startsWith("@agent-standard") ? "#67e8f9" : "#fde68a";
export const rgba = (h: string, a: number) => {
  const n = parseInt(h.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
};
export const ease = (u: number) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
/** The current board's ease-out for a hop. */
export const easeO = (u: number) => 1 - Math.pow(1 - u, 3);
/** The ring an arrival shows at `age`, 0 to 1 over PULSE: one ring, never a second a beat behind it. */
export const arrivalRings = (age: number): number[] => (age > 0 && age < 1 ? [age] : []);

/** A task's session in one machine of the machine ledger. */
export type LTask = { flow: string; agent: RawAgent };
/** What the pointer is over, or what a navigator search result stands for. */
export type Hover =
  | { kind: "mtask"; o: MachineTask }
  | { kind: "ltask"; o: LTask }
  | { kind: "task"; o: Body }
  | { kind: "dag"; o: Star }
  | { kind: "state"; o: MState }
  | { kind: "planet"; o: Planet }
  | { kind: "sun"; o: Sun }
  | { kind: "galaxy"; o: Galaxy }
  | { kind: "moon"; o: Moon }
  | { kind: "sat"; o: SubState }
  | { kind: "medge"; o: MEdge }
  | { kind: "row"; o: RowView }
  | { kind: "rstate"; o: RowView["nodes"][number] }
  | { kind: "bedge"; o: BEdge }
  | { kind: "tie"; o: Orbiter }
  | { kind: "hub"; o: Hub }
  | { kind: "link"; o: Hop }
  | { kind: "caption"; o: LedgerView["cols"][number] }
  | { kind: "lrow"; o: LedgerRow }
  | { kind: "lstep"; o: GNode }
  | { kind: "ljunction"; o: LedgerView }
  | { kind: "ldoctor"; o: ContractReport };

/** What the drawing reads of the frame, each read when a primitive runs: the canvas, the absolute zoom `K`, the zoom beyond the level's fit `ZS`,
 *  the ambient clock, the Admin type scale and what the pointer is on. */
export interface DrawCtx {
  readonly cx: CanvasRenderingContext2D;
  readonly K: number;
  readonly ZS: number;
  readonly clock: number;
  readonly scale: number;
  readonly hover: Hover | null;
}

export function drawing(dc: DrawCtx) {
  const { cx } = dc;
  const isHot = (kind: Hover["kind"], o: unknown) => !!dc.hover && dc.hover.kind === kind && dc.hover.o === o;
  /** A name's width in the type the ledger draws it in, so the layout places names by the width they take. */
  const nameWidth = (s: string, size: number, weight = 300) => {
    const was = cx.letterSpacing;
    cx.font = `${weight} ${size}px Inter, system-ui, sans-serif`;
    cx.letterSpacing = "0.6px";
    const w = cx.measureText(s).width;
    cx.letterSpacing = was; // measured mid-draw, so the text drawn after it keeps its spacing
    return w;
  };
  /** The page's crumb and clock float over the canvas: the boxes they cover, in the ledger's own pixels, and where the crumb ends. */
  function text(s: string, x: number, y: number, size: number, col: string, align: CanvasTextAlign = "center", weight = 400) {
    cx.font = `${weight} ${size}px Inter, system-ui, sans-serif`;
    cx.fillStyle = col;
    cx.textAlign = align;
    cx.textBaseline = "middle";
    cx.fillText(s, x, y);
  }
  const labPx = (n: number) => labelPx(n, dc.K, dc.scale);
  // names sit outside their node in a light, translucent face (the same see-through weight as the flow lines); a hovered node's name firms up
  function label(name: string, x: number, y: number, hot: boolean, sub?: string | null, size = 12.5) {
    size = labelPx(size, dc.K, dc.scale); // type is a fixed size on screen: readable at fit, never balloons when zoomed in; the Admin font size scales it
    cx.letterSpacing = `${0.6 / dc.K}px`;
    text(name, x, y, size, rgba("#cfd9ea", hot ? 0.95 : 0.58), "center", 300);
    if (sub) text(sub, x, y + size + 3 / dc.K, size - labelPx(2, dc.K, dc.scale), rgba("#94a3b8", hot ? 0.8 : 0.42), "center", 300);
    cx.letterSpacing = "0px";
  }
  function circle(x: number, y: number, r: number, stroke: string, w = 1, dash?: number[] | null) {
    cx.strokeStyle = stroke;
    cx.lineWidth = w;
    cx.setLineDash(dash || []);
    cx.beginPath();
    cx.arc(x, y, r, 0, TAU);
    cx.stroke();
    cx.setLineDash([]);
  }
  function dot(x: number, y: number, r: number, fill: string) {
    cx.fillStyle = fill;
    cx.beginPath();
    cx.arc(x, y, r, 0, TAU);
    cx.fill();
  }
  function disc(x: number, y: number, r: number, col: string, hot: boolean, alpha = 0.16) {
    const grd = cx.createRadialGradient(x, y, 0, x, y, r);
    grd.addColorStop(0, rgba(col, alpha));
    grd.addColorStop(1, rgba(col, 0.02));
    cx.fillStyle = grd;
    cx.beginPath();
    cx.arc(x, y, r, 0, TAU);
    cx.fill();
    circle(x, y, r, rgba(col, hot ? 0.9 : 0.4), hot ? 2 : 1.2);
  }
  /** A terminal state as a black hole: a lensing halo in the state's colour, a shadow darker than the sky, one bright photon ring and a faint outer edge. */
  function hole(x: number, y: number, r: number, col: string, hot: boolean) {
    const rs = r * 0.6, g = cx.createRadialGradient(x, y, rs, x, y, r);
    g.addColorStop(0, rgba(col, hot ? 0.42 : 0.28));
    g.addColorStop(1, rgba(col, 0));
    cx.fillStyle = g;
    cx.beginPath();
    cx.arc(x, y, r, 0, TAU);
    cx.fill();
    dot(x, y, rs, "#010205");
    circle(x, y, rs, rgba(col, hot ? 1 : 0.85), hot ? 2 : 1.4);
    circle(x, y, r, rgba(col, hot ? 0.5 : 0.14), 1);
  }
  // the current board's hop: a tapering tail (alpha and width grow toward the head), then a glowing head, in the mover's model colour
  function comet(p0: Pt, c: Pt, p1: Pt, u: number, r = 3, col = ACT) {
    const n = 14, span = 0.27 * Math.min(1, u + 0.05);
    for (let i = 1; i <= n; i++) {
      const a = bez(p0, c, p1, Math.max(0, u - span * (1 - (i - 1) / n))), b = bez(p0, c, p1, Math.max(0, u - span * (1 - i / n)));
      cx.strokeStyle = rgba(col, (i / n) * 0.6);
      cx.lineWidth = ((i / n) * 2.6) / Math.max(1, dc.ZS * 0.8);
      cx.beginPath();
      cx.moveTo(a.x, a.y);
      cx.lineTo(b.x, b.y);
      cx.stroke();
    }
    const h = bez(p0, c, p1, u), gr = 14 / dc.ZS;
    cx.globalCompositeOperation = "lighter";
    const g = cx.createRadialGradient(h.x, h.y, 0, h.x, h.y, gr);
    g.addColorStop(0, rgba(col, 0.7));
    g.addColorStop(1, rgba(col, 0));
    cx.fillStyle = g;
    cx.beginPath();
    cx.arc(h.x, h.y, gr, 0, TAU);
    cx.fill();
    cx.globalCompositeOperation = "source-over";
    dot(h.x, h.y, r, rgba(col, 0.95));
  }
  // an arrival's ring: one ring, radius eased out, fading fast; sized in screen terms so a hard zoom keeps it small
  function pulse(x: number, y: number, r: number, age: number, col = ACT, grow = 38) {
    for (const q of arrivalRings(age)) {
      circle(x, y, r + (easeO(q) * grow) / dc.ZS, rgba(col, Math.pow(1 - q, 2) * 0.85), (2 * (1 - q) + 0.4) / dc.ZS);
    }
  }
  function flowLine(a: Pt & { color: string }, b: Pt & { color: string }, alpha: number, heat: number, dash = [2, 5]) {
    const g = cx.createLinearGradient(a.x, a.y, b.x, b.y);
    g.addColorStop(0, rgba(a.color, alpha));
    g.addColorStop(1, rgba(b.color, alpha));
    cx.strokeStyle = g;
    cx.lineWidth = (1 + heat * 1.5) / Math.min(1, dc.K) ** 0.5 / Math.max(1, dc.ZS);
    cx.setLineDash(dash.map((d) => (d / dc.K) * 1.2));
    cx.lineDashOffset = ((-dc.clock * 12) / dc.K) * 1.2;
  }
  /** `s` cut to `max` px at `size`, ending in an ellipsis when it was cut. */
  function fitText(s: string, max: number, size: number) {
    cx.font = `400 ${size}px Inter, system-ui, sans-serif`;
    if (cx.measureText(s).width <= max) return s;
    let lo = 0, hi = s.length;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (cx.measureText(`${s.slice(0, mid)}…`).width <= max) lo = mid;
      else hi = mid - 1;
    }
    return `${s.slice(0, lo)}…`;
  }
  /** A stroked polyline at screen weight `w`. */
  function stroke(pts: Pt[], col: string, w = 1, dash?: number[]) {
    cx.strokeStyle = col;
    cx.lineWidth = w / dc.K ** 0.5;
    cx.setLineDash((dash ?? []).map((d) => d / dc.K));
    cx.beginPath();
    pts.forEach((p, i) => (i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y)));
    cx.stroke();
    cx.setLineDash([]);
  }
  /** A rail: the dashed stream the page draws for every action, brighter and moving while its DAG runs; a cue's dots are sparser. */
  function rail(pts: (Pt & { c?: Pt })[], a: string, b: string, heat: number, cue: boolean) {
    flowLine({ ...pts[0], color: a }, { ...pts[pts.length - 1], color: b }, (cue ? 0.32 : 0.45) + heat * 0.45, heat, cue ? [1.5, 7] : [2, 5]);
    cx.beginPath();
    pts.forEach((p, i) => (i ? (p.c ? cx.quadraticCurveTo(p.c.x, p.c.y, p.x, p.y) : cx.lineTo(p.x, p.y)) : cx.moveTo(p.x, p.y)));
    cx.stroke();
    cx.setLineDash([]);
  }
  function arrow(from: Pt, to: Pt, col: string, size: number) {
    const a = Math.atan2(to.y - from.y, to.x - from.x), s = size / dc.K;
    cx.fillStyle = col;
    cx.beginPath();
    cx.moveTo(to.x, to.y);
    cx.lineTo(to.x - s * Math.cos(a - 0.4), to.y - s * Math.sin(a - 0.4));
    cx.lineTo(to.x - s * Math.cos(a + 0.4), to.y - s * Math.sin(a + 0.4));
    cx.closePath();
    cx.fill();
  }
  function badge(p: Pt, nums: number[], col: string) {
    const s = nums.join(" · "), w = Math.max(16 / dc.K, textW(s, 10.5) / dc.K + 10 / dc.K), h = 16 / dc.K;
    cx.fillStyle = "rgba(6,10,20,0.96)";
    cx.strokeStyle = rgba(col, 0.95);
    cx.lineWidth = 1.2 / dc.K;
    cx.beginPath();
    cx.roundRect(p.x - w / 2, p.y - h / 2, w, h, h / 2);
    cx.fill();
    cx.stroke();
    text(s, p.x, p.y + 0.5 / dc.K, 10.5 / dc.K, "#fef3c7", "center", 600);
  }
  function pill(s: string, x: number, y: number, col: string) {
    const w = textW(s, 10.5) / dc.K + 12 / dc.K, h = 17 / dc.K;
    cx.fillStyle = "rgba(6,10,20,0.92)";
    cx.strokeStyle = rgba(col, 0.6);
    cx.lineWidth = 1 / dc.K;
    cx.beginPath();
    cx.roundRect(x - w / 2, y - h / 2, w, h, 4 / dc.K);
    cx.fill();
    cx.stroke();
    text(s, x, y + 0.5 / dc.K, 10.5 / dc.K, "#f8fafc", "center", 500);
  }

  /** A Board state's or a fold end's body: a black hole where a task's lifecycle ends, else its disc. */
  const body = (o: Pt & { id: string; name: string; r: number; color: string; final: boolean }, hot: boolean) => {
    if (terminal(o)) hole(o.x, o.y, o.r, o.color, hot);
    else disc(o.x, o.y, o.r, o.color, hot);
  };
  const drawTrackRings = (host: { x: number; y: number; rings?: number[] }, col: string) => {
    for (const R of host.rings || []) circle(host.x, host.y, R, rgba(col, 0.11));
  };
  // a lifecycle machine is a flat disc with a thin ring outside it, the one mark that tells it from a state
  function machine(x: number, y: number, r: number, hot: boolean, alpha: number, mapped = false) {
    const col = mapped ? EXT : "#c084fc";
    disc(x, y, r, col, hot, alpha);
    circle(x, y, r + 3, rgba(col, hot ? 0.9 : 0.5), 1);
  }
  /** A machine's name; a mapped machine's name and source are in its colour, and the pair keeps the alignment the name had. */
  function machineName(s: string, x: number, y: number, size: number, col: string, align: CanvasTextAlign, src?: string) {
    if (!src) return text(s, x, y, size, col, align, 300);
    cx.font = `300 ${size}px Inter, system-ui, sans-serif`;
    const wm = cx.measureText(s).width, gap = size * 0.45, ws = cx.measureText(src).width, x0 = align === "left" ? x : align === "right" ? x - wm - gap - ws : x - (wm + gap + ws) / 2;
    text(s, x0, y, size, rgba(EXT, 0.95), "left", 300);
    text(src, x0 + wm + gap, y, size, rgba(EXT, 0.6), "left", 300);
  }

  return { nameWidth, text, labPx, label, circle, dot, isHot, disc, hole, comet, pulse, flowLine, fitText, stroke, rail, arrow, badge, pill, body, drawTrackRings, machine, machineName };
}
/** The primitives, bound to one frame's context. */
export type Drawing = ReturnType<typeof drawing>;
