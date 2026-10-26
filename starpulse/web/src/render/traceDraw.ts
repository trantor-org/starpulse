// The traced task's drawing: the path a hovered, pinned or rail-spotted task took through the level showing, lit over a dark veil, and the note
// naming the source a mapped machine's level is observed from. It draws from the frame's context and primitives (draw.ts) and from what the
// renderer owns (`TraceIO`, read as it draws); the renderer calls each in its frame order (`drawScene`).
import { EXT, OFF, TRACE, rgba, tierColor, type Drawing, type DrawCtx, type Hover } from "./draw";
import type { Level } from "./levels";
import { bez, curveOf, stateR, type Curve, type Pt, type Scene } from "./scene";
import type { Sky } from "./sky";
import { mix, routeOf, type RouteOf } from "./transit";
import type { Target } from "../features/level/search";
import { draws, layout as traceLayout, sessionRings, type MachineStep, type Place, type Run, type Subject } from "../features/level/trace";

/** What the renderer owns and the trace's drawing reads as it draws; each is read when a frame draws, so the renderer's own state is never copied. */
export interface TraceIO {
  readonly S: Sky | null;
  readonly scene: Scene | null;
  readonly hover: Hover | null;
  readonly pin: Subject | null;
  /** The pointer, null while it is off the canvas. */
  readonly mouse: object | null;
  readonly spotted: Target | null;
  readonly W: number;
  readonly H: number;
  level(): Level;
  pinnable(s: Subject): boolean;
  runFor(s: Subject): Run | "loading" | "unavailable";
  /** The machine paths `/api/history` has answered for a task, by machine; a machine not yet read is absent. */
  walked(task: string, machines: string[]): Record<string, MachineStep[]>;
  sourceOf(flow: string | null | undefined): string | undefined;
}

type Mode = "board" | "state" | "machine";

/** A dot's path back through its phase tree: the line it rode, shaded machine into machine, the stations it walked and the machines in the order it walked them. */
export interface Trail {
  pts: (Pt & { c: string; k?: string })[];
  stations: (Pt & { c: string; k?: string })[];
  machines: string[];
}
/** A dot's route out of its sun's hub, up its own branch from the station it forked from, lit as `/api/history` says it was walked: a station shows
 *  only where its machine's path landed in its step, and the fork and the dot's own stay lit; the machines it rode come in the order their first events
 *  came (the route's own order while none has history). Where the machine changes, the colour blends over the stretch between the stations either side. */
export function trailOf({ run, end }: RouteOf, walked: Record<string, MachineStep[]>): Trail {
  const isStation = (p: { k?: string }) => /:\d+$/.test(p.k ?? ""), pts: (Pt & { c: string; k?: string; machine: string })[] = [...run, end], seen = [...new Set(run.map((n) => n.machine).filter(Boolean))];
  const first = (m: string) => walked[m]?.[0]?.at ?? Infinity, read = seen.filter((m) => walked[m]?.length);
  const machines = read.length ? read.sort((a, b) => first(a) - first(b)) : seen;
  const cum = pts.reduce<number[]>((c, q, i) => (c.push(i ? c[i - 1] + Math.hypot(q.x - pts[i - 1].x, q.y - pts[i - 1].y) : 0), c), []);
  const blended = [...pts];
  for (let j = 1; j < pts.length; j++) {
    if (pts[j].c === pts[j - 1].c) continue;
    const from = Math.max(0, pts.slice(0, j).findLastIndex(isStation)), next = pts.findIndex((p, i) => i >= j && isStation(p)), to = next < 0 ? pts.length - 1 : next;
    for (let i = from + 1; i < to; i++) blended[i] = { ...pts[i], c: mix(pts[from].c, pts[to].c, (cum[i] - cum[from]) / (cum[to] - cum[from] || 1)) };
  }
  const last = (i: number) => !run.slice(i + 1).some((n) => isStation(n) && n.machine === run[i].machine);
  const stations = run.filter((n, i) => {
    if (!isStation(n)) return false;
    const states = walked[n.machine]?.map((r) => r.state);
    return !states || states.includes(n.step ?? "") || last(i);
  });
  return { pts: blended, stations, machines };
}

export interface TraceDrawing {
  drawTrace(): void;
  drawSource(): void;
  /** The name a trace shows for a state level's body, by the name its trail gives it. */
  planetName(name: string): string;
}

export function traceDraw(dc: DrawCtx, pen: Drawing, io: TraceIO): TraceDrawing {
  const { cx } = dc;
  const { text, labPx, label, circle, dot, arrow, badge, pill } = pen;
  /** Where the traced task sits now, or null when this level does not draw it. */
  function bodyOf(s: Subject): (Pt & { model: string }) | null {
    const sc = io.scene!;
    if (s.kind === "task") return sc.tasks.find((t) => t.id === s.id && !t.gone) ?? null;
    const m = sc.machineTasks.find((t) => t.id === s.id && t.machine === s.flow);
    return m && m._x !== undefined ? { x: m._x, y: m._y!, model: m.model } : null;
  }
  /** A state level's body by the name its trail gives it, and the name a trace shows for it. */
  // a trail host is a body's name, or `primary#state` for a state of the primary
  const planetOf = (name: string) => io.scene!.planets.find((p) => p.name === name.split("#")[0]);
  const planetName = (name: string) => {
    const p = planetOf(name), st = name.includes("#") ? p?.states[name.split("#")[1]] : undefined;
    return st ? st.name : p ? p.title || p.label || p.name : name;
  };
  const placesOf = (mode: Mode): Record<string, Place> => {
    const sc = io.scene!, { K } = dc;
    // a state level's bodies: the primary's rim is its dark halo, a moon's or sub-state's its disc
    if (mode === "state") return Object.fromEntries(sc.planets.flatMap((p) => {
      const r = p.moon || p.subState ? p.R : p.R + 14, states = p.primary ? Object.values(p.states) : [];
      return [
        [p.name, { id: p.name, name: planetName(p.name), x: p.x, y: p.y, r, R: r + 12 / K, color: p.subState ? "#e879f9" : p.moon ? "#c4b5fd" : "#c084fc", lab: { x: p.x, y: p.y + r + 16 / K } }],
        ...states.map((m) => {
          const id = `${p.name}#${m.id}`, mr = stateR(m);
          return [id, { id, name: m.name, x: m.x, y: m.y, r: mr, R: mr + 8 / K, color: m.color, lab: m.lab ?? { x: m.x, y: m.y + mr + 12 } }];
        }),
      ];
    }));
    if (mode === "board") return Object.fromEntries(Object.values(sc.galaxies).map((g) => [g.id, { id: g.id, name: g.name, x: g.x, y: g.y, r: g.r, R: g.R, color: g.color, lab: { x: g.x, y: g.y + g.text[0].y * (sc.labelScale ?? 1) * (sc.px ?? 1) } }]));
    return Object.fromEntries(Object.values(sc.mStates).map((m) => {
      const r = stateR(m);
      return [m.id, { id: m.id, name: m.name, x: m.x, y: m.y, r, R: r + 12 / K, color: m.color, lab: m.lab ?? { x: m.x, y: m.y + r + 16 } }];
    }));
  };
  const edgeOf = (mode: Mode) => (from: string, to: string): Curve | null => {
    const sc = io.scene!;
    if (mode === "state") {
      // inside the primary, its machine's path; between bodies, the hop the level draws
      const [fa, fs] = from.split("#"), [ta, ts] = to.split("#");
      if (fs && ts) {
        const e = planetOf(from)?.edges.find((q) => q.a && q.b && q.source === fs && q.target === ts);
        return e ? curveOf(e.a!, e.b!) : null;
      }
      const h = sc.hops.find((q) => q.from === fa && q.to === ta);
      return h ? { p0: h.p0, c: h.c, p1: h.p1 } : null;
    }
    if (mode === "board") {
      const e = sc.bEdges.find((q) => q.p0 && q.source === from && q.target === to);
      return e ? { p0: e.p0!, c: e.c!, p1: e.p1! } : null;
    }
    const e = sc.mEdges.find((q) => q.a && q.b && q.source === from && q.target === to);
    return e ? curveOf(e.a!, e.b!) : null;
  };
  // A hovered task lights the path it took through this level, in order; a pinned one is the focused setting, and everything else steps back
  // under a dark veil from the click itself. A state level lights the bodies (primary, moons, sub-states) the task's session moved through.
  function drawTrace() {
    const { S, scene: sc, mouse, spotted } = io, { K, ZS } = dc;
    const t = draws(io.hover, io.pin, !mouse && spotted?.kind === "task" ? { kind: "task", id: spotted.id } : null).trace;
    if (!t || !S || !sc || !io.pinnable(t.subject)) return;
    const body = bodyOf(t.subject), mode = io.level().kind as Mode, board = mode === "board", run = io.runFor(t.subject);
    if (typeof run !== "string" && (board ? sc.bEdges.length : mode === "state" ? sc.planets.length : sc.mEdges.length)) {
      const { routes, pills, first } = traceLayout(run, placesOf(mode), edgeOf(mode), board, K), thick = 2.6 / Math.max(1, ZS);
      if (t.veil) {
        const m = cx.getTransform(), dpr = devicePixelRatio || 1;
        cx.setTransform(dpr, 0, 0, dpr, 0, 0);
        cx.fillStyle = "rgba(4,6,11,0.66)";
        cx.fillRect(0, 0, io.W, io.H);
        cx.setTransform(m);
      }
      for (const r of routes) {
        const { p0, c, p1 } = r.curve, g = cx.createLinearGradient(r.from.x, r.from.y, r.to.x, r.to.y);
        g.addColorStop(0, rgba(r.off ? OFF : r.from.color, 0.95));
        g.addColorStop(1, rgba(r.off ? OFF : r.to.color, 0.95));
        cx.strokeStyle = g;
        cx.lineWidth = thick;
        cx.setLineDash(r.off ? [5 / K, 5 / K] : []);
        cx.beginPath();
        for (let i = 0; i <= 24; i++) {
          const q = bez(p0, c, p1, r.t0 + ((r.t1 - r.t0) * i) / 24);
          if (i) cx.lineTo(q.x, q.y);
          else cx.moveTo(q.x, q.y);
        }
        cx.stroke();
        cx.setLineDash([]);
        arrow(bez(p0, c, p1, r.t1 - 0.02), bez(p0, c, p1, r.t1), rgba(r.off ? OFF : r.to.color, 0.95), 9);
      }
      // each visited state's rim and name firm up, with the time it held the task beside it
      for (const p of pills) {
        circle(p.place.x, p.place.y, p.place.r, rgba(p.place.color, 1), 2.2 / Math.max(1, ZS));
        if (mode !== "state") label(p.place.name, p.place.lab.x, p.place.lab.y, true, null, board ? 13 : 12.5); // a state level's bodies keep their own names
        pill(p.text, p.x, p.y, p.place.color);
      }
      for (const r of routes) badge(r.badge, r.nums, r.off ? OFF : TRACE);
      if (first) {
        circle(first.x, first.y, first.r, rgba(first.color, 0.9), 1.6 / Math.max(1, ZS));
        if (board) label(first.name, first.lab.x, first.lab.y, true, null, 13);
      }
      // on the Board, the lifecycle machines the task has sessions in: the moon is ringed with the count, and a sub-state it holds too
      if (board) {
        const ses = sessionRings(S.flows, t.subject.id, sc.moons, sc.subStates);
        for (const [m, n] of ses.moons) {
          circle(m.x, m.y, (m.r ?? 8) + 6, rgba(TRACE, 0.95), 1.6 / Math.max(1, ZS));
          text(`${n} session${n === 1 ? "" : "s"}`, m.x, m.y - (m.r ?? 8) - 14 / K, labPx(9.5), TRACE, "center", 600);
        }
        for (const m of ses.subs) circle(m.x, m.y, (m.r ?? 6) + 5, rgba(TRACE, 0.95), 1.4 / Math.max(1, ZS));
      }
    }
    // a rail-spotted task the level draws no dot for still has its path; its state body is lit in its place
    if (!body) return;
    // a dot out on a phase or sub-machine branch lights the line it rode there as a state route is lit: each leg shaded from the colour
    // of the place it leaves to the one it reaches (hub, then the machine's), each station it passed firmed up, an arrow into the dot
    const route = board ? routeOf(t.subject.id, sc) : null;
    const trail = route ? trailOf(route, io.walked(t.subject.id.split("~")[0], [...new Set(route.run.map((n) => n.machine).filter(Boolean))])) : null;
    if (trail) {
      const thick = 2.6 / Math.max(1, ZS);
      cx.lineCap = "round";
      for (let i = 1; i < trail.pts.length; i++) {
        const p = trail.pts[i - 1], q = trail.pts[i], g = cx.createLinearGradient(p.x, p.y, q.x, q.y);
        g.addColorStop(0, rgba(p.c, 0.95));
        g.addColorStop(1, rgba(q.c, 0.95));
        cx.strokeStyle = g;
        cx.lineWidth = thick;
        cx.beginPath();
        cx.moveTo(p.x, p.y);
        cx.lineTo(q.x, q.y);
        cx.stroke();
      }
      for (const s of trail.stations) circle(s.x, s.y, 4 / K, rgba(s.c, 1), 2.2 / Math.max(1, ZS));
      const n = trail.pts.length, a = trail.pts[n - 2], b = trail.pts[n - 1], l = Math.hypot(b.x - a.x, b.y - a.y);
      if (l > 10 / K) arrow(a, { x: b.x - ((b.x - a.x) / l) * (9 / K), y: b.y - ((b.y - a.y) / l) * (9 / K) }, rgba(b.c, 0.95), 9);
    }
    circle(body.x, body.y, 9 / K, rgba(TRACE, 0.9), 1.6 / K);
    dot(body.x, body.y, 4.5 / K, rgba(tierColor(body.model), 1));
  }
  /** A mapped machine's level names, above its states and in its colour, whose events move it. */
  function drawSource() {
    const lv = io.level(), { K } = dc, src = lv.kind === "machine" ? io.sourceOf(lv.flow) : undefined, st = Object.values(io.scene!.mStates);
    if (!src || !st.length) return;
    const top = Math.min(...st.map((s) => s.y)), xs = st.map((s) => s.x);
    cx.letterSpacing = `${0.6 / K}px`;
    text(`mapped from ${src} · ${src} moves it, StarPulse observes`, (Math.min(...xs) + Math.max(...xs)) / 2, top - 70 / K, labPx(11), rgba(EXT, 0.8), "center", 300);
    cx.letterSpacing = "0px";
  }
  return { drawTrace, drawSource, planetName };
}
