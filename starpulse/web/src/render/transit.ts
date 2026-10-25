import { rgba, type DrawCtx } from "./draw";
import type { Curve, NameBox, Pt } from "./scene";
import { mergePhases, type Sky } from "./sky";

/** The `--phase` and `--submachine` tokens of style.css, for the canvas: a phase machine's branch, and a sub-machine's ray. */
export const PHASE = "#38bdf8";
export const SUBMACHINE = "#2dd4bf";

export const STEP = 18;
export const CLEAR = 10;

/** A Board state's sun: the hub a task's phase branches leave, and how far out its own drawing reaches. */
export interface Hub extends Pt {
  id: string;
  edge: number;
}
/** What a task asks of the map: the stations of its phase machine and the sub-machines opened from some of them. */
export interface Want {
  task: string;
  sun: string;
  stations: number;
  subs: { at: number; stations: number }[];
}
export interface Ray {
  at: number;
  stations: Pt[];
}
export interface Branch {
  task: string;
  sun: string;
  stations: Pt[];
  rays: Ray[];
}
export interface Obstacles {
  curves: Curve[];
  names: NameBox[];
}

const TAU = Math.PI * 2;
/** Where a hub's first lane runs, past its drawing; each further lane lies this far beyond the one inside. */
const GAP = 24;
const LANE = 4 * STEP;
const LANES = 12;
/** The angles tried round a hub, so a branch lands the same place every frame. */
const TURNS = 72;

const near = (a: Pt, b: Pt, d: number) => Math.hypot(a.x - b.x, a.y - b.y) < d;
const inBox = (p: Pt, b: NameBox, pad: number) => p.x > b.x0 - pad && p.x < b.x1 + pad && p.y > b.y0 - pad && p.y < b.y1 + pad;
const sample = ({ p0, c, p1 }: Curve, n = 40): Pt[] =>
  Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return { x: u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, y: u * u * p0.y + 2 * u * t * c.y + t * t * p1.y };
  });
const points = (b: Branch): Pt[] => [...b.stations, ...b.rays.flatMap((r) => r.stations)];

/** `want` laid on the lane of radius `r` starting at angle `a`: stations a station-step apart along the arc, each sub-machine's ray straight out from its parent station. */
function lay(hub: Hub, want: Want, r: number, a: number): Branch {
  const turn = STEP / r;
  const angles = Array.from({ length: want.stations }, (_, i) => a + i * turn);
  const at = (rad: number, ang: number): Pt => ({ x: hub.x + Math.cos(ang) * rad, y: hub.y + Math.sin(ang) * rad });
  return {
    task: want.task,
    sun: want.sun,
    stations: angles.map((ang) => at(r, ang)),
    rays: want.subs.map(({ at: i, stations }) => ({ at: i, stations: Array.from({ length: stations }, (_, k) => at(r + (k + 1) * STEP, angles[i])) })),
  };
}

/** Each wanted task's branch: kept where `prior` had it, else on the nearest free place round its hub, clear of the Board's curves and names, of the other hubs and of every other branch. A task no longer wanted drops its branch. */
export function placeBranches(hubs: Hub[], wants: Want[], clear: Obstacles = { curves: [], names: [] }, prior: Branch[] = []): Branch[] {
  const byId = new Map(hubs.map((h) => [h.id, h]));
  const lines = clear.curves.flatMap((c) => sample(c));
  const kept = new Map(prior.map((b) => [b.task, b]));
  const placed: Branch[] = [];
  const free = (b: Branch) =>
    points(b).every(
      (p) =>
        !lines.some((q) => near(p, q, CLEAR)) &&
        !clear.names.some((n) => inBox(p, n, CLEAR)) &&
        !hubs.some((h) => near(p, h, h.edge + CLEAR)) &&
        !placed.some((o) => points(o).some((q) => near(p, q, STEP))),
    );
  const holds = (want: Want) => {
    const had = kept.get(want.task);
    return had && had.sun === want.sun && byId.has(want.sun) && had.stations.length === want.stations && had.rays.length === want.subs.length ? had : undefined;
  };
  placed.push(...wants.flatMap((w) => holds(w) ?? []));
  for (const want of wants.filter((w) => !holds(w))) {
    const hub = byId.get(want.sun);
    if (!hub) continue;
    const tries = Array.from({ length: LANES * TURNS }, (_, n) => lay(hub, want, hub.edge + GAP + Math.floor(n / TURNS) * LANE, ((n % TURNS) * TAU) / TURNS));
    placed.push(tries.find(free) ?? tries[tries.length - 1]);
  }
  return placed;
}

/** What each task sitting in a Board state's phase machine asks of the map: that machine's states as stations, and a ray of the sub-machine's states from each station that opens one. */
export function wantsOf(sky: Pick<Sky, "flows" | "board">): Want[] {
  const opens = (state: string, flow: string) => sky.board.machine.submachines?.some((m) => m.state === state && m.machine === flow);
  return mergePhases(sky)
    .filter((run) => opens(run.sun, run.flow))
    .map(({ task, sun, flow }) => {
      const states = sky.flows[flow].machine.states.map((st) => st.id);
      const subs = (sky.flows[flow].machine.submachines ?? []).flatMap((m) => {
        const at = states.indexOf(m.state);
        const opened = sky.flows[m.machine];
        return at < 0 || !opened ? [] : [{ at, stations: opened.machine.states.length }];
      });
      return { task, sun, stations: states.length, subs };
    });
}

/** Branches as lines through their stations, a phase machine's in `PHASE`, each sub-machine's ray in `SUBMACHINE`, from the hub they leave; `lit` brightens one task's. */
export function drawBranches(dc: DrawCtx, hubs: Hub[], branches: Branch[], lit?: string) {
  const { cx, K } = dc;
  const byId = new Map(hubs.map((h) => [h.id, h]));
  const path = (pts: Pt[], color: string, alpha: number) => {
    cx.beginPath();
    pts.forEach((p, i) => (i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y)));
    cx.strokeStyle = rgba(color, alpha);
    cx.lineWidth = 1.2 / K;
    cx.stroke();
    cx.fillStyle = rgba(color, Math.min(1, alpha + 0.3));
    for (const p of pts.slice(1)) {
      cx.beginPath();
      cx.arc(p.x, p.y, 2.6 / K, 0, TAU);
      cx.fill();
    }
  };
  for (const b of branches) {
    const hub = byId.get(b.sun);
    const alpha = b.task === lit ? 0.9 : 0.45;
    if (hub) path([hub, ...b.stations], PHASE, alpha);
    for (const r of b.rays) path([b.stations[r.at], ...r.stations], SUBMACHINE, alpha);
  }
}
