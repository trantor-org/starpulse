// The machine ledger's drawing: the template across a state level's top, the lane of machines under it, the scroll rail with its 24 h strip,
// and the path a hovered or pinned task takes through them, all in screen pixels (machineLedger.ts places them). It draws from the frame's
// context and from what the renderer owns (`LedgerIO`, read as it draws), and keeps what it drew this frame (`Ledger`) for the renderer's
// hit testing.
import type { MachineEntry, RawAgent } from "../api";
import { sizes as ledgerSizes, slot as ledgerSlot } from "../features/level/machineLedger";
import { entryAt, entryPath, PAGE, rowLabels } from "../features/level/machineLanes";
import type { Paging } from "../features/level/machinePaging";
import { emptyNote, rowMeta, stuckCount } from "../features/level/machineRows";
import { thumbOf, windowOf, type Thumb } from "../features/level/machineScroll";
import { stripLabel, stripScale, ticks, viewSpan, type Tick } from "../features/level/machineStrip";
import { sessionsOf, traceSteps, type Spot } from "../features/level/machineTrace";
import { ACT, OFF, easeO, rgba, tierColor, type Drawing, type DrawCtx, type LTask } from "./draw";
import { RAMP, bez, curveOf, type Curve, type Pt, type RowView, type Scene } from "./scene";
import { PULSE, TRAVEL, type Move, type Sky } from "./sky";

type Box = { x0: number; y0: number; x1: number; y1: number };
/** What the scroll rail is under the pointer: the back-to-newest chip, the thumb, a tick of the strip or the footer. */
export type Rail = { kind: "thumb" } | { kind: "chip" } | { kind: "foot" } | { kind: "tick"; tick: Tick };
/** What the ledger drew this frame: each task's dot, each state and each name, for the hover, the trace and the names over the veil. */
type LSpot = Pt & { r: number; color: string; y0: number; y1: number; row?: number };
type LLabel = { key: string; text: string; x: number; y: number; px: number; ink: number; ga: number; weight: number; hot: boolean; lead?: Pt & { to: number }; y0: number; y1: number };

/** What the renderer owns and the ledger reads as it draws; each is read when a frame draws, so the renderer's own state is never copied. */
export interface LedgerIO {
  readonly S: Sky | null;
  readonly scene: Scene | null;
  /** The ledger's canvas size in pixels. */
  readonly FW: number;
  readonly H: number;
  /** Now, in seconds. */
  readonly T: number;
  readonly hotEdge: Set<string>;
  events(): Move[];
  hhmm(sec: number): string;
  readonly scrollPos: number;
  readonly pg: Paging | null;
  /** The row picked out on the top machine's level. */
  readonly pickedRow: string | null;
  /** The machine and session of the pinned task. */
  readonly lpin: { flow: string; id: string } | null;
  readonly railHover: Rail | null;
  /** Whether the scroll thumb is being dragged. */
  readonly thumbDrag: boolean;
  /** The row that glows after stepping back out onto it; the ledger clears it once it has faded. */
  glow: { name: string; t0: number } | null;
}

export interface Ledger {
  tasks: { o: LTask; x: number; y: number }[];
  labs: LLabel[];
  spots: Map<string, LSpot>;
  rowNames: Map<string, { text: string; x: number; y: number; px: number }>;
  ltasks: Map<string, LTask>;
  /** Where the rail was drawn this frame, in the ledger's pixels, for the hover and the clicks. */
  railBox: { thumbX: number; laneTop: number; chip: Box | null; foot: Box | null; stripT: number; sx0: number; sx1: number };
  thumb: Thumb | null;
  ticks: Tick[];
  rowTop: Map<string, number>;
  /** Where each row is drawn this frame (down the canvas), for the hover. */
  lane: { row: RowView; y: number; to: number }[];
  /** A row is still easing to its place, so the next frame is wanted. */
  sliding: boolean;
  drawTop(): void;
  /** One object per session while its snapshot stands, so the hover card is rewritten only when the session changes. */
  ltaskOf(flow: string, agent: RawAgent): LTask;
  pinnedTask(): LTask | null;
  /** Whether the ledger lays out a state: the top machine's, or a row's. */
  ledgerHas(s: Spot): boolean;
}

export function machineLedger(dc: DrawCtx, d: Drawing, io: LedgerIO): Ledger {
  const { cx } = dc;
  const { text, circle, dot, comet, pulse, flowLine, fitText, arrow, nameWidth, isHot } = d;
  const led: Ledger = {
    tasks: [], labs: [], spots: new Map(), rowNames: new Map(), ltasks: new Map(),
    railBox: { thumbX: 0, laneTop: 0, chip: null, foot: null, stripT: 0, sx0: 0, sx1: 0 },
    thumb: null, ticks: [], rowTop: new Map(), lane: [], sliding: false,
    drawTop, ltaskOf, pinnedTask, ledgerHas,
  };
  function ledgerHas(s: Spot) {
    const top = io.scene!.top!;
    return s.machine === top.flow ? top.nodes.some((n) => n.id === s.state) : !!top.rows.find((r) => r.name === s.machine)?.nodes.some((n) => n.id === s.state);
  }
  // ---- the machine across a state level's top, in screen pixels (machineLedger.ts places it; the type and dots grow with the square root of the text size) ----
  const INK = "#cfd9ea", SUB = "#94a3b8", DAGC = "#fcd34d", PLANET = RAMP[4];
  /** A flow line between two states, trimmed to their discs. */
  function flowBetween(a: Pt & { color: string; r: number }, b: Pt & { color: string; r: number }, bend: number, alpha: number, heat: number, dash?: number[]) {
    const c = curveOf(a, b, bend), len = Math.hypot(b.x - a.x, b.y - a.y) || 1, t0 = Math.min(0.4, (a.r + 1) / len), t1 = 1 - Math.min(0.4, (b.r + 2) / len);
    flowLine(a, b, alpha, heat, dash);
    cx.beginPath();
    for (let i = 0; i <= 16; i++) {
      const q = bez(c.p0, c.c, c.p1, t0 + ((t1 - t0) * i) / 16);
      if (i) cx.lineTo(q.x, q.y);
      else cx.moveTo(q.x, q.y);
    }
    cx.stroke();
    cx.setLineDash([]);
  }
  /** Each task orbits the state its latest move left it on; one that moved just now rides the flow line there as a comet. `seen` is told where each is drawn. */
  function orbitTasks(
    flow: string, agents: { id: string; state: string; model?: string }[], where: (state: string) => (Pt & { r: number }) | undefined,
    bend: (from: string, to: string) => number, seen?: (id: string, at: Pt | null, state: string) => void, big?: (id: string) => boolean,
  ) {
    const scale = dc.scale, { gs, dot: dr } = ledgerSizes(scale), seat: Record<string, number> = {};
    for (const s of agents) {
      const ev = io.events().findLast((m) => m.task === s.id && m.flow === flow && m.at <= io.T), state = ev ? ev.to : s.state, cur = where(state);
      if (!cur) {
        seen?.(s.id, null, state);
        continue;
      }
      const prev = ev?.from && ev.from !== state ? where(ev.from) : undefined, u = ev ? (io.T - ev.at) / TRAVEL : 9;
      if (prev && u < 1) {
        const c = curveOf(prev, cur, bend(ev!.from!, state)), q = bez(c.p0, c.c, c.p1, easeO(u));
        comet(c.p0, c.c, c.p1, easeO(u), dr * 1.5, tierColor(s.model));
        seen?.(s.id, q, state);
        continue;
      }
      const pa = ev ? (io.T - ev.at - TRAVEL) / PULSE : 9;
      if (prev && pa >= 0 && pa < 1) pulse(cur.x, cur.y, 3, pa, ACT, 18 * gs); // the task landed: one ring where it sits
      const sl = ledgerSlot(cur.r, (seat[state] = (seat[state] ?? 0) + 1) - 1, scale), th = sl.a + dc.clock * 0.06, p = { x: cur.x + sl.R * Math.cos(th), y: cur.y + sl.R * Math.sin(th) };
      seen?.(s.id, p, state);
      dot(p.x, p.y, big?.(s.id) ? dr * 1.5 : dr, rgba(tierColor(s.model), 0.9));
    }
  }
  /** A DAG launch: the star, and its dashed line to the machine's first state. */
  function launch(sx: number, sy: number, to: Pt & { r: number; color: string }, gs: number) {
    flowBetween({ x: sx, y: sy, r: 7, color: DAGC }, to, 0, 0.4, 0, [1, 4]);
    dot(sx, sy, 11 * gs, rgba(DAGC, 0.12));
    cx.fillStyle = rgba(DAGC, 0.9);
    cx.beginPath();
    for (let i = 0; i < 8; i++) {
      const r = (i % 2 ? 0.3 : 1) * 5.5 * gs, th = (i * Math.PI) / 4 - Math.PI / 2;
      cx.lineTo(sx + r * Math.cos(th), sy + r * Math.sin(th));
    }
    cx.closePath();
    cx.fill();
  }
  function drawTop() {
    const sc = io.scene!, top = sc.top!, scale = dc.scale, { fs, gs } = ledgerSizes(scale), nodes = new Map(top.nodes.map((n) => [n.id, n]));
    const flow = io.S!.flows[top.flow], stuck = stuckCount(io.S!.flows, top.ranked);
    const name = 12 * fs, sub = 10 * fs, mx = top.metaX, mw = top.metaW;
    led.tasks = [];
    led.labs = [];
    led.spots.clear();
    led.rowNames.clear();
    // the template's own name and what it holds, then the machines entered from it, over the spine under the header
    cx.letterSpacing = "0.6px";
    text(fitText(top.flow, mw, name * 1.08), mx, top.metaT + 4 + name * 0.6, name * 1.08, rgba(INK, 0.9), "left", 400);
    text(fitText(`template · ${top.nodes.length} states · ${flow?.agents.length ?? 0} tasks`, mw, sub), mx, top.metaT + 6 + name * 1.3 + sub * 0.6, sub, rgba(SUB, 0.7), "left", 300);
    const count = (ink: number) => text(fitText(`${top.total} machine${top.total === 1 ? "" : "s"}${top.task ? ` holding ${top.task}` : stuck ? ` · ${stuck} stuck` : " · newest first"}`, mw, sub), mx, top.hdrB - sub, sub, rgba(SUB, ink), "left", 300);
    count(0.6);
    cx.letterSpacing = "0px";
    cx.fillStyle = rgba(SUB, 0.16);
    cx.fillRect(mx - 10, top.hdrB, top.x1 + 22 - mx, 1);
    for (const id of top.entered) {
      const n = nodes.get(id);
      if (n) dot(n.x, top.hdrB + 0.5, 2.2 * gs, rgba(sc.mStates[id].color, 0.9)); // a state some machine is entered from marks the hairline
    }
    cx.save();
    cx.beginPath();
    cx.rect(0, 0, io.FW, top.hdrB);
    cx.clip();
    for (const e of sc.mEdges) {
      const a = e.a && nodes.get(e.a.id), b = e.b && nodes.get(e.b.id);
      if (!e.a || !e.b || !a || !b || e.a === e.b) continue;
      const hot = dc.hover?.kind === "state" && (dc.hover.o === e.a || dc.hover.o === e.b), heat = io.hotEdge.has(`${e.flow}:${e.source}>${e.target}`) ? 1 : 0;
      flowBetween({ x: a.x, y: a.y, r: a.r, color: e.a.color }, { x: b.x, y: b.y, r: b.r, color: e.b.color }, e.bend ?? 0.08, Math.min(1, (hot || isHot("medge", e) ? 0.95 : 0.4) + heat * 0.5), heat + (hot ? 0.8 : 0));
    }
    // a state: a coloured rim and centre over a faint wash of its own colour; a final state has a second ring
    for (const n of top.nodes) {
      const col = sc.mStates[n.id].color, hot = isHot("state", sc.mStates[n.id]);
      dot(n.x, n.y, n.r, rgba(col, hot ? 0.3 : 0.12));
      circle(n.x, n.y, n.r, rgba(col, hot ? 1 : 0.85), hot ? 2 : 1.6);
      if (n.final) circle(n.x, n.y, n.r + 2.5, rgba(col, 0.45), 1);
      dot(n.x, n.y, Math.min((n.initial ? 5.5 : 4) * gs, n.r * 0.4), rgba(col, 0.9));
      led.spots.set(`${top.flow}:${n.id}`, { x: n.x, y: n.y, r: n.r, color: col, y0: 0, y1: top.hdrB });
    }
    // a DAG that launches this machine itself: its star left of the first state
    const first = top.nodes.find((n) => n.initial) ?? top.nodes[0];
    (flow?.ties ?? []).filter((t) => t.kind === "dag").forEach((_, k) => first && launch(first.x - first.orbit - 14, first.y + k * 14, { ...first, color: sc.mStates[first.id].color }, gs));
    // each task orbits the state its latest move left it on
    orbitTasks(top.flow, sc.machineTasks, (st) => nodes.get(st), (from, to) => sc.mEdges.find((e) => e.a === sc.mStates[from] && e.b === sc.mStates[to])?.bend ?? 0.28, (id, at, state) => {
      const s = sc.machineTasks.find((q) => q.id === id)!;
      s._x = at?.x;
      s._y = at?.y;
      if (at) s._state = state;
      if (at) led.tasks.push({ o: ltaskOf(top.flow, s), x: at.x, y: at.y });
    }, (id) => dc.hover?.kind === "ltask" && dc.hover.o.flow === top.flow && dc.hover.o.agent.id === id);
    // names: beside or against a state, or on a hairline from it when crowded; drawn last, over the trace
    for (const l of top.labels) {
      const cy = l.y + l.h / 2;
      led.labs.push({ key: `${top.flow}:${l.id}`, text: l.text, x: l.x, y: cy, px: l.px, ink: 0.7, ga: 1, weight: top.entered.includes(l.id) ? 400 : 300, hot: isHot("state", sc.mStates[l.id]), lead: l.lead ? { ...l.lead, to: l.lead.y > cy ? l.y + l.h : l.y } : undefined, y0: 0, y1: top.hdrB });
    }
    cx.restore();
    drawLane();
    drawRail();
    // a pinned path is the focused setting: the rest of the ledger steps back under the page's dark veil
    if (pinnedTask()) {
      cx.fillStyle = "rgba(4,6,11,0.66)";
      cx.fillRect(0, 0, io.FW, io.H);
      cx.letterSpacing = "0.6px";
      count(0.9); // the count names the task the rows are narrowed to, over the veil
      cx.letterSpacing = "0px";
    }
    drawLedgerLabels(drawLedgerTrace());
  }
  /** What the ledger drew this frame: each task's dot, each state and each name, for the hover, the trace and the names over the veil. */
  /** One object per session while its snapshot stands, so the hover card is rewritten only when the session changes. */
  function ltaskOf(flow: string, agent: RawAgent): LTask {
    const k = `${flow}:${agent.id}`, o = led.ltasks.get(k);
    if (o?.agent === agent) return o;
    const n = { flow, agent };
    led.ltasks.set(k, n);
    return n;
  }
  function pinnedTask(): LTask | null {
    const a = io.lpin && io.S?.flows[io.lpin.flow]?.agents.find((x) => x.id === io.lpin!.id);
    return a ? ltaskOf(io.lpin!.flow, a) : null;
  }
  const clipY = (y0: number, y1: number, fn: () => void) => {
    cx.save();
    cx.beginPath();
    cx.rect(0, y0, io.FW, y1 - y0);
    cx.clip();
    fn();
    cx.restore();
  };
  type LPath = Curve | ReturnType<typeof entryPath>;
  const pathAt = (e: LPath, t: number) => ("c1" in e ? entryAt(e, t) : bez(e.p0, e.c, e.p1, t));
  const badgeW = (s: string) => {
    cx.font = "600 10px Inter, system-ui, sans-serif";
    return Math.max(16, cx.measureText(s).width + 10);
  };
  function stepBadge(p: Pt, s: string, col: string) {
    const w = badgeW(s), h = 15;
    cx.fillStyle = "rgba(6,10,20,0.92)";
    cx.strokeStyle = rgba(col, 0.95);
    cx.lineWidth = 1.1;
    cx.beginPath();
    cx.roundRect(p.x - w / 2, p.y - h / 2, w, h, h / 2);
    cx.fill();
    cx.stroke();
    text(s, p.x, p.y + 0.5, 10, "#fef3c7", "center", 600);
  }
  /**
   * The hovered task's path, else the pinned one's, across every machine of the ledger it has a session in: each hop retraced along the flow line
   * it took in the colours of its two states, a hop with no line bowing off red and dashed, an entry dropping from the state it left; numbered in
   * order, its states' rims firmed and its rows named over the veil, and its own dots ringed. Returns the states it lit.
   */
  function drawLedgerTrace(): Set<string> {
    const src = dc.hover?.kind === "ltask" ? dc.hover.o : pinnedTask(), sc = io.scene!, top = sc.top!;
    if (!src || !io.S) return new Set();
    const key = (s: Spot) => `${s.machine}:${s.state}`, sessions = sessionsOf(io.S.flows, src.flow, src.agent);
    const steps = traceSteps(io.S.flows, sessions, top.flow, ledgerHas).filter((s) => led.spots.has(key(s.a)) && led.spots.has(key(s.b)));
    const lit = new Set(steps.flatMap((s) => [key(s.a), key(s.b)]));
    const bendOf = (a: LSpot, b: LSpot, from: string, to: string) =>
      a.row === undefined ? (sc.mEdges.find((e) => e.a === sc.mStates[from] && e.b === sc.mStates[to])?.bend ?? 0.08) : b.x < a.x - 1 ? Math.min(0.28, (a.row * 0.6) / (Math.hypot(b.x - a.x, b.y - a.y) || 1)) : 0.04;
    const geo = steps.map((s) => {
      const a = led.spots.get(key(s.a))!, b = led.spots.get(key(s.b))!, len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const e: LPath = s.kind === "entry" ? entryPath(a, b) : curveOf(a, b, s.off ? (a.row === undefined ? 0.28 : Math.min(0.28, (a.row * 0.6) / (Math.abs(b.x - a.x) || 1))) : bendOf(a, b, s.a.state, s.b.state));
      return { s, a, b, e, t0: Math.min(0.4, (a.r + 2) / len), t1: 1 - Math.min(0.4, (b.r + 4) / len), y0: s.kind === "entry" ? 0 : a.y0, y1: s.kind === "entry" ? top.laneBottom : a.y1 };
    });
    for (const { s, a, b, e, t0, t1, y0, y1 } of geo)
      clipY(y0, y1, () => {
        const g = cx.createLinearGradient(a.x, a.y, b.x, b.y);
        g.addColorStop(0, rgba(s.off ? OFF : a.color, 0.95));
        g.addColorStop(1, rgba(s.off ? OFF : b.color, 0.95));
        cx.strokeStyle = g;
        cx.lineWidth = 2.4;
        cx.setLineDash(s.off ? [5, 5] : []);
        cx.beginPath();
        for (let i = 0; i <= 24; i++) {
          const q = pathAt(e, t0 + ((t1 - t0) * i) / 24);
          if (i) cx.lineTo(q.x, q.y);
          else cx.moveTo(q.x, q.y);
        }
        cx.stroke();
        cx.setLineDash([]);
        arrow(pathAt(e, t1 - 0.02), pathAt(e, t1), rgba(s.off ? OFF : b.color, 0.95), 8);
      });
    // each state the path visits: its rim firms up, and a row's name comes back over the veil
    for (const k of lit) {
      const n = led.spots.get(k)!;
      clipY(n.y0, n.y1, () => circle(n.x, n.y, n.r, rgba(n.color, 1), 2));
    }
    cx.letterSpacing = "0.6px";
    for (const m of new Set(steps.flatMap((s) => [s.a.machine, s.b.machine]))) {
      const r = led.rowNames.get(m);
      if (r) clipY(top.laneTop, top.laneBottom, () => text(r.text, r.x, r.y, r.px, rgba(INK, 0.97), "left", 400));
    }
    cx.letterSpacing = "0px";
    // step numbers at each line's middle, a line taken twice carrying both, slid along it clear of the others
    const byLine = new Map<string, { g: (typeof geo)[number]; nums: number[] }>();
    for (const g of geo) {
      const k = `${key(g.s.a)}>${key(g.s.b)}>${g.s.kind}`;
      if (!byLine.has(k)) byLine.set(k, { g, nums: [] });
      byLine.get(k)!.nums.push(g.s.n);
    }
    const taken: Pt[] = [];
    for (const { g, nums } of byLine.values()) {
      const txt = nums.join(" · "), w = badgeW(txt) + 4, h = 19, along = (t: number) => pathAt(g.e, g.t0 + (g.t1 - g.t0) * t);
      const p = [0.5, 0.38, 0.62, 0.28, 0.72].map(along).find((q) => !taken.some((o) => Math.abs(o.x - q.x) < w && Math.abs(o.y - q.y) < h)) ?? along(0.5);
      taken.push(p);
      clipY(g.y0, g.y1, () => stepBadge(p, txt, g.s.off ? OFF : ACT));
    }
    // the traced task's own dots, ringed
    for (const s of sessions) {
      const t = led.tasks.find((q) => q.o.flow === s.machine && q.o.agent.id === s.agent.id);
      if (t) circle(t.x, t.y, 6, rgba(ACT, 0.95), 1.4);
    }
    return lit;
  }
  /** The ledger's state names, over the trace: under a pinned path's veil they dim, except the states the path visits. */
  function drawLedgerLabels(lit: Set<string>) {
    const veil = pinnedTask() ? 0.4 : 1;
    cx.letterSpacing = "0.6px";
    for (const l of led.labs)
      clipY(l.y0, l.y1, () => {
        const hot = l.hot || lit.has(l.key);
        cx.globalAlpha = l.ga * (hot ? 1 : veil);
        if (l.lead) {
          cx.strokeStyle = rgba(INK, 0.22);
          cx.lineWidth = 1;
          cx.beginPath();
          cx.moveTo(l.lead.x, l.lead.y);
          cx.lineTo(l.lead.x, l.lead.to);
          cx.stroke();
        }
        text(l.text, l.x, l.y, l.px, rgba(INK, hot ? 0.95 : l.ink), "left", l.weight);
        cx.globalAlpha = 1;
      });
    cx.letterSpacing = "0px";
  }
  /** The colour a tick takes: the state its machine was entered from, amber for a DAG launch. */
  function entryColor(e: MachineEntry): string {
    const sc = io.scene!, top = sc.top!;
    if (e.dag != null) return DAGC;
    if (!e.from) return PLANET;
    if (e.from.machine === top.flow) return sc.mStates[e.from.state]?.color ?? PLANET;
    const st = io.S!.flows[e.from.machine]?.machine.states ?? [], j = st.findIndex((s) => s.id === e.from!.state);
    return j < 0 ? PLANET : RAMP[Math.round((st.length > 1 ? j / (st.length - 1) : 0) * (RAMP.length - 1))];
  }
  /** The thumb, the back-to-newest chip and the strip of the last 24 h of machine entries under the lane, with the rows in view shaded on it. */
  function drawRail() {
    const top = io.scene!.top!, { fs } = ledgerSizes(dc.scale), sp = 10 * fs, stripT = top.laneBottom, sx0 = top.metaX, sx1 = top.x1, hot = hotRow();
    cx.fillStyle = rgba(SUB, 0.16);
    cx.fillRect(top.metaX - 10, stripT, top.x1 + 20 - top.metaX, 1);
    led.thumb = thumbOf(top.content, { h: stripT - top.laneTop, fs }, io.scrollPos, top.max);
    Object.assign(led.railBox, { thumbX: top.x1 + 18, laneTop: top.laneTop, stripT, sx0, sx1, chip: null, foot: null });
    if (led.thumb) {
      const t = led.thumb, x = led.railBox.thumbX;
      cx.fillStyle = rgba(SUB, 0.08);
      cx.fillRect(x - 1, top.laneTop + t.y0, 2, t.y1 - t.y0);
      cx.fillStyle = rgba(SUB, io.railHover?.kind === "thumb" || io.thumbDrag ? 0.65 : 0.32);
      cx.beginPath();
      cx.roundRect(x - 2, top.laneTop + t.ty, 4, t.th, 2);
      cx.fill();
    }
    if (top.more) {
      const footY = top.laneTop + top.content - top.foot - io.scrollPos;
      led.railBox.foot = { x0: top.metaX - 10, x1: top.x1 + 20, y0: Math.max(top.laneTop, footY), y1: Math.min(stripT, footY + top.foot) };
    }
    if (io.scrollPos > 8) {
      const label = "↑ back to newest", w = nameWidth(label, sp) + 24 * fs, h = 20 * fs, x0 = (top.x0 + top.x1) / 2 - w / 2, y0 = top.laneTop + 8;
      led.railBox.chip = { x0, y0, x1: x0 + w, y1: y0 + h };
      cx.beginPath();
      cx.roundRect(x0, y0, w, h, h / 2);
      cx.fillStyle = "rgba(12,19,34,0.92)";
      cx.fill();
      cx.strokeStyle = `rgba(167,139,250,${io.railHover?.kind === "chip" ? 0.7 : 0.35})`;
      cx.lineWidth = 1;
      cx.stroke();
      cx.letterSpacing = "0.6px";
      text(label, x0 + w / 2, y0 + h / 2, sp, rgba(INK, 0.9), "center", 400);
      cx.letterSpacing = "0px";
    }
    // the strip: one continuous stretch shaded for the rows in view, a tick per entry, hours along the axis
    const scale = stripScale(sx0, sx1, io.T), by = stripT + 30 * fs;
    led.ticks = ticks(io.S!.machineEntries, top.ranked, scale);
    const inView = windowOf(top.rows, io.scrollPos, { h: stripT - top.laneTop, fs }).inView.map((i) => io.S!.flows[top.rows[i].name]?.last ?? null), span = viewSpan(inView, scale.t0);
    if (span) {
      const a = scale.x(span.from), b = scale.x(span.to);
      cx.fillStyle = rgba(PLANET, 0.12);
      cx.fillRect(a - 3, by - 14 * fs, b - a + 6, 14 * fs);
      cx.fillStyle = rgba(PLANET, 0.5);
      cx.fillRect(a - 3, by, b - a + 6, 1);
    }
    cx.fillStyle = rgba(SUB, 0.22);
    cx.fillRect(sx0, by, sx1 - sx0, 1);
    cx.letterSpacing = "0.6px";
    for (let h = Math.ceil(scale.t0 / 10800) * 10800; h <= scale.t1; h += 10800) {
      const x = scale.x(h);
      cx.fillStyle = rgba(SUB, 0.3);
      cx.fillRect(x, by, 1, 4);
      if (x - sx0 > 18 && sx1 - x > 18) text(io.hhmm(h), x, by + 11 * fs, sp * 0.95, rgba(SUB, 0.5), "center", 300);
    }
    for (const t of led.ticks) {
      const on = hot === t.entry.row || (io.railHover?.kind === "tick" && io.railHover.tick === t), len = (on ? 13 : 8) * fs;
      cx.fillStyle = rgba(entryColor(t.entry), on ? 1 : 0.62);
      cx.fillRect(t.x - 0.75, by - len, 1.5, len);
    }
    text("24 h · machine entries", sx0, stripT + 8 * fs, sp, rgba(SUB, 0.6), "left", 300);
    text(stripLabel(span, top.rows.length, top.total, io.hhmm), sx1, stripT + 8 * fs, sp, rgba(SUB, 0.7), "right", 300);
    cx.letterSpacing = "0px";
  }
  /** The row the pointer is on, over its name or one of its states. */
  const hotRow = () => (dc.hover?.kind === "row" ? dc.hover.o.name : dc.hover?.kind === "rstate" ? (io.scene!.top!.rows.find((r) => r.nodes.includes((dc.hover as { o: RowView["nodes"][number] }).o))?.name ?? null) : null);
  /** The band at a row's foot that shows where its nesting is (machineChain.ts): each state's stem in its colour, then a block per machine entered from it. */
  function drawChain(row: RowView, y: number, on: boolean) {
    const sp = 10 * ledgerSizes(dc.scale).fs, al = on ? 0.95 : 0.72, col = new Map(row.nodes.map((n) => [n.id, n.color])), ramp = (j: number, n: number) => RAMP[Math.round((j / Math.max(1, n - 1)) * (RAMP.length - 1))];
    const fit = (t: string, w: number) => {
      if (nameWidth(t, sp) <= w) return t;
      let s = t;
      while (s.length > 1 && nameWidth(`${s}…`, sp) > w) s = s.slice(0, -1);
      return `${s}…`;
    };
    cx.lineWidth = 1;
    for (const c of row.chain!.cols) {
      cx.save();
      cx.beginPath();
      cx.rect(c.clip.x0, y, c.clip.x1 - c.clip.x0, row.h);
      cx.clip();
      for (const st of c.stems) {
        cx.strokeStyle = rgba(col.get(st.state) ?? PLANET, al * 0.7);
        cx.beginPath();
        st.pts.forEach((p, i) => (i ? cx.lineTo(p.x, y + p.y) : cx.moveTo(p.x, y + p.y)));
        for (const d of st.drops) {
          cx.moveTo(d.x, y + d.y0);
          cx.lineTo(d.x, y + d.y1);
        }
        cx.stroke();
      }
      for (const b of c.blocks) {
        for (const l of b.lines) {
          cx.strokeStyle = rgba(SUB, 0.35 * al * l.a);
          cx.beginPath();
          cx.moveTo(l.x, y + l.y);
          cx.lineTo(l.x + (l.states.length - 1) * l.dx, y + l.y);
          cx.stroke();
          l.states.forEach((_, j) => dot(l.x + j * l.dx, y + l.y, l.r, rgba(ramp(j, l.states.length), al * l.a)));
        }
        cx.setLineDash([1.5, 2]);
        for (const h of b.hangs) {
          cx.strokeStyle = rgba(PLANET, al * h.a);
          cx.beginPath();
          cx.moveTo(h.x, y + h.y0);
          cx.lineTo(h.x, y + h.y1);
          cx.stroke();
        }
        cx.setLineDash([]);
        const lab = fit(b.name, Math.max(12, b.label.w - (b.tail ? nameWidth(b.tail, sp) : 0)));
        cx.letterSpacing = "0.6px";
        text(lab, b.label.x, y + b.label.y, sp, rgba(PLANET, al), "left", 300);
        if (b.tail) text(b.tail, b.label.x + nameWidth(lab, sp), y + b.label.y, sp, rgba(SUB, 0.75), "left", 300);
        cx.letterSpacing = "0px";
      }
      cx.restore();
    }
  }
  /** The machine ledger's rows under the top: each machine entered from it, newest activity first, with its tie, its stuck mark and its DAG launches. */
  function drawLane() {
    const sc = io.scene!, top = sc.top!, scale = dc.scale, { fs, gs } = ledgerSizes(scale), mx = top.metaX, mw = top.metaW, nameP = 12 * fs, subP = 10 * fs, top0 = new Map(top.nodes.map((n) => [n.id, n]));
    const hot = hotRow(), hs = dc.hover?.kind === "state" ? dc.hover.o : null, now = io.T, fl = io.glow ? Math.max(0, 1 - (performance.now() - io.glow.t0) / 1600) : 0;
    if (!fl) io.glow = null;
    cx.save();
    cx.beginPath();
    cx.rect(0, top.laneTop, io.FW, top.laneBottom - top.laneTop);
    cx.clip();
    // a faint guide down the lane from each state some row is entered from
    for (const id of top.entered) {
      const n = top0.get(id);
      if (!n) continue;
      cx.strokeStyle = rgba(sc.mStates[id].color, hs?.id === id ? 0.35 : 0.1);
      cx.lineWidth = 1;
      cx.setLineDash([2, 5]);
      cx.beginPath();
      cx.moveTo(n.x, top.hdrB + 3);
      cx.lineTo(n.x, top.laneBottom);
      cx.stroke();
      cx.setLineDash([]);
    }
    // each row eases to its place, so a row that moves slides (and fades while it does)
    led.sliding = false;
    led.lane = top.rows.map((row) => {
      const to = top.laneTop + row.y, was = led.rowTop.get(row.name), eased = was === undefined || Math.abs(was - to) > 1500 ? to : Math.abs(to - was) < 0.3 ? to : was + (to - was) * 0.3;
      led.rowTop.set(row.name, eased);
      if (eased !== to) led.sliding = true;
      return { row, y: eased - io.scrollPos, to: to - io.scrollPos };
    });
    if (fl) led.sliding = true; // the glow fades over frames
    if (!top.rows.length) text(emptyNote(top.flow), (top.x0 + top.x1) / 2, (top.laneTop + top.laneBottom) / 2, subP, rgba(SUB, 0.6), "center", 300);
    const shown = led.lane.filter(({ row, y }) => y + row.h > top.laneTop && y < top.laneBottom);
    const pos = (row: RowView, y: number) => new Map(row.nodes.map((n) => [n.id, { x: n.x, y: y + row.c + n.oy, r: n.r, color: n.color, orbit: n.orbit }]));
    const spots = new Map(shown.map((d) => [d.row.name, pos(d.row, d.y)])); // only the rows in view are placed
    for (const { row, y, to: place } of shown) {
      const f = io.S!.flows[row.name], m = rowMeta(io.S!.flows, row.name, top.flow, now), ns = spots.get(row.name)!, picked = io.pickedRow === row.name, on = hot === row.name || picked, fade = Math.abs(y - place) > 3 ? 0.3 : 1;
      for (const [id, p] of ns) led.spots.set(`${row.name}:${id}`, { ...p, y0: top.laneTop, y1: top.laneBottom, row: row.h });
      cx.globalAlpha = fade;
      const lit = Math.max(on ? (picked ? 0.09 : 0.055) : 0, io.glow?.name === row.name ? 0.16 * fl : 0);
      if (lit) {
        cx.fillStyle = rgba(PLANET, lit);
        cx.fillRect(mx - 10, y, top.x1 + 20 - mx, row.h);
      }
      cx.fillStyle = rgba(SUB, 0.09);
      cx.fillRect(mx - 10, y + row.h - 1, top.x1 + 20 - mx, 1);
      if (m.status.stuck) {
        cx.fillStyle = rgba(OFF, 0.85);
        cx.fillRect(mx - 10, y + 6, 2, row.h - 12);
      }
      // the notch under the column of the template state this machine is entered from: filled when declared, hollow when observed
      const src = m.tie.machine === top.flow && m.tie.state ? top0.get(m.tie.state) : undefined;
      if (src && m.tie.state) {
        const col = rgba(sc.mStates[m.tie.state].color, 0.95);
        cx.fillStyle = col;
        cx.strokeStyle = col;
        cx.lineWidth = 1.2;
        cx.beginPath();
        cx.moveTo(src.x - 4.5, y + 1.5);
        cx.lineTo(src.x + 4.5, y + 1.5);
        cx.lineTo(src.x, y + 8);
        cx.closePath();
        if (m.tie.kind === "declared") cx.fill();
        else cx.stroke();
      }
      // meta: its name, where it is entered from, and what its tasks are doing
      const ty = y + row.h / 2 - (nameP * 1.4 + 2 * subP * 1.5) / 2;
      cx.letterSpacing = "0.6px";
      const endW = nameWidth(m.end, subP) + 8;
      text(m.end, mx + mw, ty + nameP * 0.7, subP, rgba(PLANET, on ? 1 : 0.7), "right", 300);
      const nm = { text: fitText(row.name, mw - endW, nameP), x: mx, y: ty + nameP * 0.7, px: nameP };
      led.rowNames.set(row.name, nm);
      text(nm.text, nm.x, nm.y, nameP, rgba(INK, on ? 0.97 : m.status.idle ? 0.55 : 0.85), "left", 400);
      const dotCol = m.tie.kind === "none" || m.tie.kind === "dag" ? null : m.tie.machine === top.flow ? sc.mStates[m.tie.state!]?.color : (top.rows.find((q) => q.name === m.tie.machine)?.nodes.find((n) => n.id === m.tie.state)?.color ?? PLANET);
      const tieInk = m.tie.kind === "dag" ? rgba(DAGC, 0.75) : m.tie.kind === "none" ? rgba(SUB, 0.5) : rgba(INK, 0.62), ly = ty + nameP * 1.4 + subP * 0.75;
      if (dotCol) dot(mx + 3, ly, 2.6 * gs, rgba(dotCol, 0.95));
      text(fitText(m.tie.text, mw - (dotCol ? 11 : 0), subP), mx + (dotCol ? 11 : 0), ly, subP, tieInk, "left", 300);
      text(fitText(m.status.text, mw, subP), mx, ty + nameP * 1.4 + subP * 2.25, subP, m.status.stuck ? rgba(OFF, 0.9) : rgba(SUB, m.status.idle ? 0.5 : 0.7), "left", 300);
      cx.letterSpacing = "0px";
      // its DAG launches, each a star left of the first state
      const dags = (f.ties ?? []).filter((t) => t.kind === "dag"), init = ns.get(row.init)!, stars = dags.map((_, k) => ({ x: top.x0 - 18 * fs, y: y + row.c + (k - (dags.length - 1) / 2) * 12 * fs }));
      for (const s of stars) launch(s.x, s.y, init, gs);
      // the machine itself: its flow lines, states, tasks and names
      cx.globalAlpha = fade * (m.status.idle && !on ? 0.75 : 1);
      for (const t of f.machine.transitions) {
        const a = ns.get(t.source), b = ns.get(t.target);
        if (!a || !b || a === b) continue;
        flowBetween(a, b, b.x < a.x - 1 ? Math.min(0.28, (row.h * 0.6) / (Math.hypot(b.x - a.x, b.y - a.y) || 1)) : 0.04, Math.min(1, on ? 0.95 : 0.36), on ? 0.8 : 0, [1.5, 4]);
      }
      for (const n of row.nodes) {
        const p = ns.get(n.id)!, hotN = dc.hover?.kind === "rstate" && dc.hover.o === n;
        dot(p.x, p.y, n.r, rgba(n.color, hotN ? 0.3 : 0.12));
        circle(p.x, p.y, n.r, rgba(n.color, hotN ? 1 : 0.85), hotN ? 2 : 1.2);
        if (n.final) circle(p.x, p.y, n.r + 2.5, rgba(n.color, 0.45), 1);
        dot(p.x, p.y, Math.min(3 * gs, n.r * 0.4), rgba(n.color, 0.9));
      }
      if (row.chain) drawChain(row, y, on);
      cx.globalAlpha = fade;
      orbitTasks(row.name, f.agents, (st) => ns.get(st), (from, to) => (ns.get(to)!.x < ns.get(from)!.x - 1 ? 0.28 : 0.04), (id, at) => {
        const a = at && at.y > top.laneTop && at.y < top.laneBottom && f.agents.find((q) => q.id === id);
        if (a) led.tasks.push({ o: ltaskOf(row.name, a), x: at.x, y: at.y });
      });
      for (const l of rowLabels(row, { scale, measure: (t, px) => nameWidth(t, px), x0: top.x0, x1: top.x1 }, stars.map((q) => ({ x: q.x, y: q.y - y, r: 11 }))))
        led.labs.push({ key: `${row.name}:${l.id}`, text: l.text, x: l.x, y: y + l.y + l.h / 2, px: l.px, ink: on ? 0.85 : 0.5, ga: fade, weight: 300, hot: dc.hover?.kind === "rstate" && dc.hover.o.id === l.id && on, y0: top.laneTop, y1: top.laneBottom });
      cx.globalAlpha = 1;
    }
    if (top.more) {
      const footY = top.laneTop + top.content - top.foot - io.scrollPos, busy = io.pg?.busy, wait = io.pg?.failedAt != null && !busy;
      cx.letterSpacing = "0.6px";
      text(busy ? `loading ${Math.min(PAGE, top.more)} more…` : wait ? `could not load ${Math.min(PAGE, top.more)} more · trying again` : `${top.more} more · scroll to load`, (top.x0 + top.x1) / 2, footY + top.foot / 2, subP, rgba(wait ? OFF : SUB, 0.7), "center", 300);
      cx.letterSpacing = "0px";
    }
    // a row's tie, drawn while the row or the state it is entered from is under the pointer, along the path its sessions take in; it crosses the
    // gap under the top machine, so it clips to the lane's bottom rather than its top
    cx.restore();
    cx.save();
    cx.beginPath();
    cx.rect(0, 0, io.FW, top.laneBottom);
    cx.clip();
    for (const { row } of shown) {
      const f = io.S!.flows[row.name], to = spots.get(row.name)!.get(row.init);
      if (!to) continue;
      f.ties?.forEach((t, i) => {
        if (t.kind === "dag" || !t.machine || !t.state) return;
        const a = t.machine === top.flow ? top0.get(t.state) : spots.get(t.machine)?.get(t.state);
        if (!a) return;
        const al = hot === row.name || io.pickedRow === row.name || (hs && hs.flow === t.machine && hs.id === t.state) ? (i ? 0.45 : 0.9) : 0;
        if (!al) return;
        const col = t.machine === top.flow ? sc.mStates[t.state].color : (a as { color: string }).color, e = entryPath(a, to), len = Math.hypot(to.x - a.x, to.y - a.y) || 1, t0 = Math.min(0.4, (a.r + 2) / len), t1 = 1 - Math.min(0.4, (to.r + 3) / len);
        flowLine({ x: a.x, y: a.y, color: col }, { x: to.x, y: to.y, color: to.color }, al, 0.5, t.kind === "observed" ? [1.5, 6] : [2, 5]);
        cx.beginPath();
        for (let k = 0; k <= 28; k++) {
          const q = entryAt(e, t0 + ((t1 - t0) * k) / 28);
          if (k) cx.lineTo(q.x, q.y);
          else cx.moveTo(q.x, q.y);
        }
        cx.stroke();
        cx.setLineDash([]);
        arrow(entryAt(e, t1 - 0.02), entryAt(e, t1), rgba(to.color, al), 7 * gs);
      });
    }
    cx.restore();
  }

  return led;
}
