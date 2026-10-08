// The DAGs tied to a Board state, drawn on the Star Map as a hangar per state: its DAGs orbit the state just outside its ring, each turned
// toward the transition it acts on, with the hangar's name beside them. Which DAGs are tied, the state each belongs to, and where each orbiter
// and name sits; the renderer draws them (drawHub). A DAG that only launches work, or has no tie, stays off the map (the DAGs view lists it).
//   write — the DAG writes a Board transition (the board machine's `writers`)
//   cue   — a Board event cues the DAG (the snapshot's `cues`)
import { bez, type BEdge, type Pt, type Scene } from "./scene";
import type { Sky } from "./sky";

export type TieKind = "write" | "cue";
export interface Anchor extends Pt {
  kind: TieKind;
  /** The Board event the tie is about. */
  event: string;
  edge?: BEdge;
  /** The state the tie acts on: a write's source (the state the DAG moves work out of), a cue's state (where the event lands). */
  state: string;
}
export interface Orbiter extends Pt {
  dag: string;
  label: string;
  anchors: Anchor[];
  /** The transition the DAG docks by: its orbiter aims at it. */
  primary?: Anchor;
  /** Its angle round the state. */
  a: number;
}
export interface Hub {
  /** The state it orbits. */
  state: string;
  /** The state's centre, and the radius of the ring its orbiters sit on, in world units. */
  c: Pt;
  orbit: number;
  orbs: Orbiter[];
  /** The hangar's name: where it is anchored, its alignment, and the room it takes. */
  lab: Pt;
  align: CanvasTextAlign;
  box: [number, number, number, number];
  /** The stretches of the ring its arc draws, clear of every name it would cross. */
  arcs: [number, number][];
}
export interface Ties {
  hubs: Hub[];
  /** World units a screen pixel at the Board's fit, and the page's text size as a factor. */
  u: number;
  ts: number;
}

const short = (d: string) => d.replace(/^[^/]+\//, "");

/** The tied DAGs of the Board level: a hangar per state with an orbiter for each DAG that writes or is cued by one of its transitions. */
export function boardTies(sc: Scene, sky: Sky, u: number, ts = 1): Ties {
  const board = sky.board.machine, byDag = new Map<string, Orbiter>();
  const tie = (dag: string): Orbiter | null => {
    if (!sky.dagBy[dag]) return null;
    let t = byDag.get(dag);
    if (!t) byDag.set(dag, (t = { dag, label: short(dag), anchors: [], x: 0, y: 0, a: 0 }));
    return t;
  };
  const edgeOf = (event: string) => [...sc.bEdges, ...sc.entries, ...sc.exits].find((e) => e.events.includes(event));
  const mid = (e: BEdge): Pt | null => (e.p0 && e.c && e.p1 ? bez(e.p0, e.c, e.p1, 0.5) : null);
  const rimOf = (id: string): Pt => {
    const g = sc.galaxies[id];
    return { x: g.x, y: g.y - g.R };
  };
  for (const [event, ws] of Object.entries(board.writers ?? {}))
    for (const w of ws) {
      const t = tie(w.actor), tr = board.transitions.find((x) => x.event === event);
      if (!t || !tr || !sc.galaxies[tr.source]) continue;
      const e = edgeOf(event), m = e && !e.loop ? mid(e) : null;
      t.anchors.push({ ...(m ?? rimOf(tr.source)), kind: "write", event, edge: e, state: tr.source });
    }
  for (const c of sky.cues) {
    const t = tie(c.dag), e = edgeOf(c.event), m = e ? mid(e) : null;
    if (t && m) t.anchors.push({ ...m, kind: "cue", event: c.event, edge: e, state: c.state || e!.target });
  }
  const all = [...byDag.values()];
  // each DAG belongs to the state most of its ties act on (the first, on a tie), and docks by one of that state's transitions
  const home = (t: Orbiter) => {
    const n = new Map<string, number>();
    for (const a of t.anchors) if (sc.galaxies[a.state]) n.set(a.state, (n.get(a.state) ?? 0) + 1);
    return [...n].reduce<[string, number] | null>((b, x) => (!b || x[1] > b[1] ? x : b), null)?.[0];
  };
  const own = (t: Orbiter) => t.anchors.filter((a) => a.state === home(t));
  // among them, the one whose edge holds the fewest DAGs so far, the DAGs with fewest ties choosing first
  const load = new Map<BEdge | undefined, number>();
  for (const t of all.filter((t) => own(t).length).sort((a, b) => own(a).length - own(b).length)) {
    const a = own(t).reduce((x, y) => ((load.get(y.edge) ?? 0) < (load.get(x.edge) ?? 0) ? y : x));
    load.set(a.edge, (load.get(a.edge) ?? 0) + 1);
    t.primary = a;
  }
  const byState = new Map<string, Orbiter[]>();
  for (const t of all.filter((t) => t.primary)) byState.set(t.primary!.state, [...(byState.get(t.primary!.state) ?? []), t]);
  const hubs: Hub[] = [];
  for (const [state, os] of byState) hubs.push(place(sc, state, os, hubs, u, ts));
  return { hubs, u, ts };
}

type Dir = "down" | "up" | "left" | "right";
/** The side facing away along (dx, dy). */
const outward = (dx: number, dy: number): Dir => (Math.abs(dy) >= Math.abs(dx) * 0.8 ? (dy > 0 ? "down" : "up") : dx > 0 ? "right" : "left");
/** A box and how heavily an overlap with it counts. */
type Box = [number, number, number, number, number];
/** The area two boxes share, weighted by `b`'s. */
export const over = (a: Box, b: Box) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1])) * b[4];

/** What a hangar's name and orbiters keep clear of, each padded: every state's disc (but `state`'s own) and its name and count, every moon and
 *  its full name (a zoomed-in map cuts none), and the hangars already placed with their orbiters. */
export function obstacles(sc: Scene, placed: Hub[], u: number, ts: number, state?: string): Box[] {
  const pad = 8 * u, out: Box[] = [];
  for (const s of Object.values(sc.galaxies)) {
    const R = Math.max(s.R, s.visR);
    if (s.id !== state) out.push([s.x - R - pad, s.y - R - pad, s.x + R + pad, s.y + R + pad, 1]);
    const w = (Math.max(s.name.length * 4.2, 54) + 6) * u * ts;
    out.push([s.lab.x - w - pad, s.lab.y - 16 * u * ts - pad, s.lab.x + w + pad, s.lab.y + 26 * u * ts + pad, 1]);
  }
  for (const m of sc.moons) {
    const left = m.x < m.parent.x, x0 = m.x + (left ? -1 : 1) * (m.R + m.ext + 10), w = (m.label.length * 6 + 4) * u * ts, h = 9 * u * ts;
    out.push(left ? [x0 - w - pad, m.y - h - pad, m.x + m.R + pad, m.y + h + pad, 1] : [m.x - m.R - pad, m.y - h - pad, x0 + w + pad, m.y + h + pad, 1]);
  }
  for (const h of placed) {
    out.push([...h.box, 1]);
    for (const o of h.orbs) out.push([o.x - 10 * u, o.y - 10 * u, o.x + 10 * u, o.y + 10 * u, 1]);
  }
  return out;
}

/** A state's DAGs orbit it just outside its ring, each turned toward the transition it docks by and spread so no two touch, clear of every name
 *  the ring crosses; then the hangar's name goes beside them, and the group turns round the ring (up to 90°) until the name fits. */
function place(sc: Scene, state: string, orbs: Orbiter[], placed: Hub[], u: number, ts: number): Hub {
  const g = sc.galaxies[state], gs = Object.values(sc.galaxies), R0 = Math.max(g.R, g.visR), name = widest(orbs), tall = (nameLines(orbs).length - 1) * 13 * u * ts;
  const c: Pt = { x: g.x, y: g.y }, orbit = Math.max(R0, g.moonR) + 16 * u;
  const bare = obstacles(sc, placed, u, ts);
  const x0 = Math.min(...gs.map((s) => s.x - Math.max(s.R, s.visR))) - 40 * u, x1 = Math.max(...gs.map((s) => s.x + Math.max(s.R, s.visR))) + 40 * u;
  const aim = (t: Orbiter) => Math.atan2(t.primary!.y - c.y, t.primary!.x - c.x);
  const order = [...orbs].sort((a, b) => aim(a) - aim(b));
  order.forEach((t) => (t.a = aim(t)));
  // neighbours closer than the least gap push apart, half each, until none are; the ring wraps
  const sep = Math.min((22 * u) / orbit, (Math.PI * 2) / order.length);
  const spread = () => {
    for (let pass = 0; pass < 60; pass++)
      for (let i = 0; i < order.length; i++) {
        const p = order[i], q = order[(i + 1) % order.length];
        let d = q.a - p.a;
        if (i === order.length - 1) d += Math.PI * 2;
        if (order.length < 2 || d >= sep) continue;
        p.a -= (sep - d) / 2;
        q.a += (sep - d) / 2;
      }
  };
  spread();
  // the ring crosses the state's own name and its neighbours: each orbiter takes the nearest stretch clear of them
  const ring = obstacles(sc, placed, u, ts, state), rr = 10 * u, step = Math.PI / 90;
  const posAt = (a: number) => ({ x: c.x + Math.cos(a) * orbit, y: c.y + Math.sin(a) * orbit });
  const free = (a: number) => {
    const { x, y } = posAt(a);
    return !ring.some((k) => over([x - rr, y - rr, x + rr, y + rr, 1], k) > 0);
  };
  const snap = (a: number) => {
    for (let k = 0; k <= 90; k++) for (const sg of k ? [-1, 1] : [1]) if (free(a + sg * k * step)) return a + sg * k * step;
    return a;
  };
  for (let pass = 0; pass < 6; pass++) {
    order.forEach((t) => (t.a = snap(t.a)));
    if (pass < 5) spread();
  }
  // the name right beside its orbiters, past them on the far side from the state first, then any other side of them; where no side has room,
  // the group turns a little round the ring (6° at a time, up to 90°) until one does, so the name never drifts off its DAGs
  const base = orbs.map((t) => t.a), g8 = 9 * u;
  let pick: { s: number; as: number[]; lab: Pt; align: CanvasTextAlign; box: Hub["box"] } | null = null;
  for (let k = 0; k <= 15 && pick?.s !== 0; k++)
    for (const sg of k ? [-1, 1] : [1]) {
      const as = base.map((a) => a + (sg * k * 6 * Math.PI) / 180);
      if (k && !as.every(free)) continue;
      const ps = as.map(posAt), own = ps.map((q): Box => [q.x - 9 * u, q.y - 9 * u, q.x + 9 * u, q.y + 9 * u, 1]);
      const xs = ps.map((q) => q.x), ys = ps.map((q) => q.y);
      const bx0 = Math.min(...xs) - g8, bx1 = Math.max(...xs) + g8, by0 = Math.min(...ys) - g8, by1 = Math.max(...ys) + g8, my = (by0 + by1) / 2, mx = (bx0 + bx1) / 2;
      const at: Record<Dir, [Pt, CanvasTextAlign]> = { right: [{ x: bx1 + 4 * u, y: my + 3.5 * u * ts - tall / 2 }, "left"], left: [{ x: bx0 - 4 * u, y: my + 3.5 * u * ts - tall / 2 }, "right"], down: [{ x: mx, y: by1 + (4 + 8 * ts) * u }, "center"], up: [{ x: mx, y: by0 - (4 + 10 * ts) * u - tall }, "center"] };
      const out = outward(mx - c.x, my - c.y);
      for (const dir of [out, "right", "left", "down", "up"].filter((d, i, l) => l.indexOf(d) === i) as Dir[]) {
        const [lab, align] = at[dir], box = boxOf(lab, align, name, u, ts, tall);
        const s = [...bare, ...own].reduce((n, o) => n + over([...box, 1], o), 0) + (box[0] < x0 || box[2] > x1 ? 1e9 : 0);
        if (!pick || s < pick.s) pick = { s, as, lab, align, box };
        if (s === 0) break;
      }
      if (pick?.s === 0) break;
    }
  const best = pick!;
  orbs.forEach((t, i) => Object.assign(t, { a: best.as[i] }, posAt(best.as[i])));
  // the arc: the clear stretches between its outermost orbiters, round their middle however the angles wrap, broken at its own name too
  const lb = best.box, m0 = Math.atan2(orbs.reduce((n, t) => n + Math.sin(t.a), 0), orbs.reduce((n, t) => n + Math.cos(t.a), 0));
  const as = orbs.map((t) => m0 + Math.atan2(Math.sin(t.a - m0), Math.cos(t.a - m0))), pad = (14 * u) / orbit, arcs: [number, number][] = [];
  const clear = (a: number) => {
    const q = posAt(a);
    return free(a) && over([q.x - 2 * u, q.y - 2 * u, q.x + 2 * u, q.y + 2 * u, 1], [...lb, 1]) === 0;
  };
  let run: number | null = null;
  for (let a = Math.min(...as) - pad; a <= Math.max(...as) + pad + 1e-9; a += step / 2) {
    if (clear(a)) run ??= a;
    else if (run !== null) {
      arcs.push([run, a]);
      run = null;
    }
  }
  if (run !== null) arcs.push([run, Math.max(...as) + pad]);
  return { state, c, orbit, orbs, lab: best.lab, align: best.align, box: best.box, arcs };
}

/** A hangar's name: its one DAG, or how many it holds. */
export const nameOf = (orbs: Pick<Orbiter, "label">[]) => (orbs.length === 1 ? orbs[0].label : `${orbs.length} DAGs`);
/** A hangar's name as drawn: a lone DAG's long name breaks after the hyphen nearest its middle, so it stays whole in half the width. */
export const nameLines = (orbs: Pick<Orbiter, "label">[]): string[] => {
  const n = nameOf(orbs), cuts = [...n.matchAll(/-/g)].map((m) => m.index + 1);
  if (orbs.length > 1 || n.length <= 12 || !cuts.length) return [n];
  const at = cuts.reduce((a, b) => (Math.abs(b - n.length / 2) < Math.abs(a - n.length / 2) ? b : a));
  return [n.slice(0, at), n.slice(at)];
};
/** The widest line a hangar's name shows: its longer line, when it breaks. */
const widest = (orbs: Pick<Orbiter, "label">[]) => nameLines(orbs).reduce((a, b) => (b.length > a.length ? b : a));
/** The room a hangar's name takes, anchored at `lab` and aligned `align`: one line or two when it breaks. */
const boxOf = (lab: Pt, align: CanvasTextAlign, name: string, u: number, ts: number, tall: number): Hub["box"] => {
  const tw = (name.length * 3.4 + 4) * u * ts, lines = (6 + 16 * ts) * u + tall;
  const x = align === "left" ? [lab.x, lab.x + 2 * tw] : align === "right" ? [lab.x - 2 * tw, lab.x] : [lab.x - tw, lab.x + tw];
  return [x[0], lab.y - 9 * u * ts, x[1], lab.y + lines];
};
