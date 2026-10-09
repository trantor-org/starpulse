// The Board's and the state levels' drawing: the galaxies, moons and planets with their stems, states and orbiting tasks, the DAG hangars tied to a
// state, the Board's and machines' flow lines, the sun and the DAGs' own step graphs. It draws from the frame's context and primitives (draw.ts)
// and from what the renderer owns (`BoardIO`, read as it draws); the renderer calls each in its frame order (`drawScene`).
import type { LedgerRow } from "../api";
import { fanBadge, stepStatus } from "../features/fanout/fanout";
import { stepStates } from "../features/level/ledgerPanel";
import { ACT, DAG_COLOR, EXT, easeO, rgba, tierColor, type Drawing, type DrawCtx } from "./draw";
import { nameLines, touches, type Hub, type Ties } from "./dagTies";
import {
  BOARD_COLOR, SUN_R, TAU, bez, clip, curveOf, stateR, taskSlot, terminal, textW,
  type BEdge, type Curve, type GNode, type MEdge, type MState, type Planet, type Scene,
} from "./scene";
import { FLARE, PULSE, RING, TRAVEL, countText, hosted, type Move, type Moves, type Sky } from "./sky";

/** How a tied DAG's orbiter looks: the Spinner while its DAG runs, else its last run's colour, with a dashed ring after a failed run. */
export const orbiterLook = (status: string) => ({ spin: status === "running", color: status === "queued" ? "#94a3b8" : DAG_COLOR[status] || "#94a3b8", dashed: status === "failed" });

/** The ring a DAG's run ending at `fin` has on screen at `now`, as its age from 0 to 1: one ring per event, over PULSE, never repeated. */
export const dagRings = (fin: number | undefined, now: number): number[] =>
  fin !== undefined && fin <= now && now - fin < PULSE ? [(now - fin) / PULSE] : [];

/** What the renderer owns and the Board's drawing reads as it draws; each is read when a frame draws, so the renderer's own state is never copied. */
export interface BoardIO {
  readonly S: Sky | null;
  readonly scene: Scene | null;
  /** Now, in seconds. */
  readonly T: number;
  readonly moves: Moves;
  readonly liveTasks: Set<string>;
  readonly hotEdge: Set<string>;
  events(): Move[];
  /** The moves of `flow` on their way now. */
  moving(flow: string): Move[];
  /** The value `key` shows on this level, eased from the one it showed before a snapshot changed it. */
  sized(key: string, r: number): number;
  sourceOf(flow: string | null | undefined): string | undefined;
  ties(): Ties | null;
  heldRows(): readonly LedgerRow[];
  focused(): LedgerRow | undefined;
}

export function boardDraw(dc: DrawCtx, d: Drawing, io: BoardIO) {
  const { cx } = dc;
  const { text, labPx, label, circle, dot, isHot, disc, hole, comet, pulse, flowLine, body, drawTrackRings, machine, machineName } = d;
  function drawGalaxies() {
    for (const g of Object.values(io.scene!.galaxies)) {
      const hot = isHot("galaxy", g);
      body(g, hot);
      drawTrackRings(g, g.color);
      label(g.name, g.lab.x, g.lab.y, hot, `${countText(g.n, g.today)}${g.subs.length ? ` · ${g.subs.length} lifecycles` : ""}`, 13);
    }
  }
  // lifecycle moons: still, named bodies on their state's dashed outer ring, brighter while they have sessions, ringed in amber while one moves.
  // A machine's sub-states run outward from its moon in its row on dashed stems, the machine's name past them.
  function drawMoons() {
    const sc = io.scene!;
    for (const g of Object.values(sc.galaxies)) if (sc.moons.some((m) => m.parent === g)) circle(g.x, g.y, g.moonR, rgba(g.color, isHot("galaxy", g) ? 0.6 : 0.25), 1, [2, 5]);
    for (const m of sc.moons) {
      const hot = isHot("moon", m), flows = m.pager?.hidden ?? [m.name], mv = flows.flatMap(io.moving).length, busy = flows.some((name) => !!hosted(io.S!, name, m.parent.id).length);
      drawTrackRings(m, "#c084fc");
      const src = m.pager ? undefined : io.sourceOf(m.name);
      machine(m.x, m.y, m.r!, hot, busy ? 0.32 : 0.14, !!src);
      if (mv) circle(m.x, m.y, m.r! + 4, rgba(ACT, 0.85), 1.5);
      // named beside the moon on the side away from its state, past its chain of sub-states
      const left = m.x < m.parent.x - 1;
      cx.letterSpacing = `${0.5 / dc.K}px`;
      const col = rgba("#d8c8f5", hot ? 0.95 : 0.6);
      machineName(sc.clipped ? clip(m.label) : m.label, m.x + (left ? -1 : 1) * (m.R + m.ext + 10), m.y, labPx(10.5), col, left ? "right" : "left", src);
      cx.letterSpacing = "0px";
    }
    for (const b of sc.subStates) {
      const hot = isHot("sat", b), u = Math.sign(b.x - b.prev.x) || 1, col = b.color!;
      cx.strokeStyle = rgba(col, hot ? 0.75 : 0.4);
      cx.lineWidth = 1 / dc.K ** 0.5;
      cx.setLineDash([2 / dc.K, 3 / dc.K]);
      cx.beginPath();
      cx.moveTo(b.prev.x + u * ((b.prev.r ?? b.prev.R) + 3), b.prev.y);
      cx.lineTo(b.x - u * (b.r! + 3), b.y);
      cx.stroke();
      cx.setLineDash([]);
      disc(b.x, b.y, b.r!, col, hot, 0.22);
      drawTrackRings(b, col);
    }
  }
  /** Whether a tied writer ran at a Board move: it runs now, or its latest run ended about then (a move carries no actor). */
  const ran = (dag: string, at: number) => io.S?.dagBy[dag]?.status === "running" || Math.abs((io.moves.flare[dag] ?? Infinity) - at) < FLARE;
  /** The hangars, then the moment a tied DAG writes or is cued: the ticket's own comet runs that transition's edge into its state, once per edge,
   *  and a cue rings the orbiter it wakes. Nothing marks the line at rest. The moving task rings the state it lands in, so a write adds no ring. */
  function drawTies() {
    const tz = io.ties();
    if (!tz) return;
    for (const h of tz.hubs) drawHub(h);
    const run = new Set<BEdge>();
    for (const t of touches(tz, io.events(), ran, io.T)) {
      const e = t.anchor.edge, age = (io.T - t.at - TRAVEL) / PULSE;
      if (e?.p0 && e.c && e.p1 && !e.loop && t.u < 1 && !run.has(e)) {
        run.add(e);
        comet(e.p0, e.c, e.p1, easeO(t.u), 3, ACT);
      }
      if (t.anchor.kind === "cue" && age >= 0 && age < 1) pulse(t.orbiter.x, t.orbiter.y, 5 / dc.K, age, ACT, 16);
    }
  }
  /** A hangar: a faint arc behind its orbiters, broken where it would cross a name, one orbiter per DAG and the hangar's name alone. Whether a
   *  DAG runs or failed is its orbiter's to show: the Spinner, or red with a dashed ring. */
  function drawHub(h: Hub) {
    const TEAL = "#5eead4", hubHot = isHot("hub", h);
    cx.strokeStyle = rgba(TEAL, hubHot ? 0.4 : 0.22);
    cx.lineWidth = 1 / dc.K;
    for (const [a0, a1] of h.arcs) {
      cx.beginPath();
      cx.arc(h.c.x, h.c.y, h.orbit, a0, a1);
      cx.stroke();
    }
    for (const o of h.orbs) {
      const hot = isHot("tie", o), look = orbiterLook(io.S!.dagBy[o.dag]?.status ?? ""), r = (hot ? 7 : 6) / dc.K;
      // a hovered orbiter rings the states of the machine it writes
      if (hot) for (const a of o.subs) circle(a.x, a.y, 10 / dc.K, rgba("#a78bfa", 0.9), 1.4 / dc.K, [2 / dc.K, 2 / dc.K]);
      dot(o.x, o.y, r, "rgba(6,10,20,0.95)");
      if (look.spin) {
        circle(o.x, o.y, r, rgba(look.color, 0.95), 1.3 / dc.K);
        dot(o.x, o.y, r * 0.45, rgba(look.color, 0.95));
        cx.strokeStyle = rgba(look.color, 0.9);
        cx.lineWidth = 1.4 / dc.K;
        cx.beginPath();
        cx.arc(o.x, o.y, r + 3.5 / dc.K, dc.clock * 4, dc.clock * 4 + Math.PI / 2);
        cx.stroke();
        continue;
      }
      circle(o.x, o.y, r, rgba(look.color, look.dashed || hot ? 1 : 0.6), (hot ? 1.5 : 1.2) / dc.K);
      dot(o.x, o.y, r * 0.4, rgba(look.color, look.dashed ? 0.95 : 0.7));
      if (look.dashed) circle(o.x, o.y, r + 4 / dc.K, rgba(look.color, 0.7), 1 / dc.K, [2 / dc.K, 2 / dc.K]);
    }
    const ls = labPx(11.5);
    cx.letterSpacing = `${0.6 / dc.K}px`;
    nameLines(h.orbs).forEach((n, i) => text(n, h.lab.x, h.lab.y + i * (ls + 2 / dc.K), ls, rgba("#cfd9ea", hubHot ? 0.95 : 0.58), h.align, 300));
    cx.letterSpacing = "0px";
  }
  function drawSun() {
    const s = io.scene!.sun;
    if (!s) return;
    const hot = isHot("sun", s), r = s.r;
    // a terminal state's level centres on the black hole the Board draws for it, at the same size
    if (terminal(s)) {
      hole(s.x, s.y, r, s.color, hot);
      drawTrackRings(s, s.color);
      return;
    }
    // the glow reaches five suns' radii past the sun
    const glow = cx.createRadialGradient(s.x, s.y, 0, s.x, s.y, r + 5 * SUN_R);
    glow.addColorStop(0, rgba(s.color, 0.55));
    glow.addColorStop(0.25, rgba(s.color, 0.2));
    glow.addColorStop(1, rgba(s.color, 0));
    cx.fillStyle = glow;
    cx.beginPath();
    cx.arc(s.x, s.y, r + 5 * SUN_R, 0, TAU);
    cx.fill();
    const core = cx.createRadialGradient(s.x, s.y, 0, s.x, s.y, r);
    core.addColorStop(0, "#f5f3ff");
    core.addColorStop(0.5, rgba(s.color, 0.95));
    core.addColorStop(1, rgba(s.color, 0.6));
    cx.fillStyle = core;
    cx.beginPath();
    cx.arc(s.x, s.y, r * (1 + 0.04 * Math.sin(dc.clock * 2)), 0, TAU);
    cx.fill();
    if (hot) circle(s.x, s.y, r + 5, rgba(s.color, 0.9), 1.5);
    drawTrackRings(s, s.color);
  }
  // action lines as on the current board: a dashed stroke that streams toward its target, a gradient from source colour to target colour,
  // brighter and thicker while a writer DAG has just run (or is running)
  function drawBoardEdges() {
    const sc = io.scene!;
    for (const e of sc.bEdges) {
      const lit = isHot("bedge", e) || (dc.hover?.kind === "tie" && dc.hover.o.anchors.some((a) => a.edge === e)), col = sc.galaxies[e.source].color, heat = io.hotEdge.has(`board:${e.source}>${e.target}`) ? 1 : 0;
      flowLine({ ...e.p0!, color: col }, { ...e.p1!, color: sc.galaxies[e.target].color }, lit ? 0.95 : (e.events.every((v) => v === "ARCHIVE") ? 0.1 : 0.2) + heat * 0.55, heat + (lit ? 0.8 : 0));
      cx.beginPath();
      cx.moveTo(e.p0!.x, e.p0!.y);
      cx.quadraticCurveTo(e.c!.x, e.c!.y, e.p1!.x, e.p1!.y);
      cx.stroke();
      cx.setLineDash([]);
    }
  }
  // state level: the paths between machines and the Board paths off the edges, drawn as the Board draws its transitions
  function drawStateLinks() {
    const sc = io.scene!, stroke = (l: Curve) => {
      cx.beginPath();
      cx.moveTo(l.p0.x, l.p0.y);
      cx.quadraticCurveTo(l.c.x, l.c.y, l.p1.x, l.p1.y);
      cx.stroke();
      cx.setLineDash([]);
    };
    for (const l of sc.hops) {
      const lit = isHot("link", l), heat = l.busy ? 1 : 0;
      flowLine({ ...l.p0, color: "#a78bfa" }, { ...l.p1, color: "#c084fc" }, lit ? 0.95 : 0.22 + heat * 0.55, heat + (lit ? 0.8 : 0));
      stroke(l);
    }
    for (const l of [...sc.entries, ...sc.exits]) {
      if (!l.p0) continue;
      const lit = isHot("bedge", l), heat = l.busy ? 1 : 0;
      flowLine({ ...l.p0, color: BOARD_COLOR[l.source] ?? "#94a3b8" }, { ...l.p1!, color: BOARD_COLOR[l.target] ?? "#94a3b8" }, lit ? 0.95 : (l.events.every((v) => v === "ARCHIVE") ? 0.1 : 0.2) + heat * 0.55, heat + (lit ? 0.8 : 0));
      stroke(l as Curve);
      label(l.lab!.name, l.lab!.x, l.lab!.y - 12 / dc.K, lit, null, 10.5);
    }
  }
  function drawMachineEdges(edges: MEdge[], thin = false) {
    for (const e of edges) {
      if (!e.a || !e.b) continue;
      const lit = isHot("medge", e), heat = io.hotEdge.has(`${e.flow}:${e.source}>${e.target}`) ? 1 : 0;
      if (e.a === e.b) continue; // a self-transition would sit under the orbiting tasks, so the state's tooltip lists it
      const c = curveOf(e.a, e.b), L = Math.hypot(e.b.x - e.a.x, e.b.y - e.a.y), t0 = Math.min(0.4, stateR(e.a) / L), tEnd = 1 - Math.min(0.4, (stateR(e.b) + 2) / L);
      flowLine(e.a, e.b, lit ? 0.95 : 0.2 + heat * 0.55, heat + (lit ? 0.8 : 0), thin ? [1.5, 4] : [2, 5]);
      cx.beginPath();
      for (let i = 0; i <= 16; i++) {
        const p = bez(c.p0, c.c, c.p1, t0 + ((tEnd - t0) * i) / 16);
        if (i) cx.lineTo(p.x, p.y);
        else cx.moveTo(p.x, p.y);
      }
      cx.stroke();
      cx.setLineDash([]);
    }
  }
  function drawStates(states: Record<string, MState>, labels: boolean) {
    for (const s of Object.values(states)) {
      const R = io.sized(`state|${s.flow}:${s.id}`, stateR(s)), hot = isHot("state", s);
      if (terminal(s)) {
        hole(s.x, s.y, R, s.color, hot);
        if (labels) label(s.name, s.lab ? s.lab.x : s.x, s.lab ? s.lab.y : s.y + R + 16, hot);
        continue;
      }
      dot(s.x, s.y, R, "rgba(6,10,20,0.9)");
      circle(s.x, s.y, R, rgba(s.color, hot ? 1 : s.n ? 0.85 : 0.45), hot ? 2.2 : s.mini ? 1 : 1.6);
      dot(s.x, s.y, s.mini ? 1.5 : s.initial ? 4 : 2.5, rgba(s.color, 0.9));
      if (labels) label(s.name, s.lab ? s.lab.x : s.x, s.lab ? s.lab.y : s.y + R + 16, hot);
    }
  }
  // machine level: each task sits on the state its latest machine event left it in; a move the page has just seen slides it along its edge as a comet
  function drawMachineTasks() {
    const sc = io.scene!, at: Record<string, number> = {};
    for (const s of sc.machineTasks) {
      s._x = undefined;
      const ev = io.events().findLast((e) => e.task === s.id && e.flow === s.flow && e.at <= io.T), state = ev ? ev.to : s.state;
      const cur = sc.mStates[state];
      if (!cur) continue;
      s._state = state;
      const prev = ev?.from ? sc.mStates[ev.from] : null, u = ev ? (io.T - ev.at) / TRAVEL : 9;
      if (prev && prev !== cur && u < 1) {
        const c = curveOf(prev, cur), q = bez(c.p0, c.c, c.p1, easeO(u));
        comet(c.p0, c.c, c.p1, easeO(u), 3.4, tierColor(s.model));
        s._x = q.x;
        s._y = q.y;
        continue;
      }
      const pa = ev ? (io.T - ev.at - TRAVEL) / PULSE : 9;
      if (prev && prev !== cur && pa >= 0 && pa < 1) pulse(cur.x, cur.y, stateR(cur), pa, cur.color); // the state it landed on rings once
      const k = (at[state] = (at[state] || 0) + 1) - 1, { t, rr } = taskSlot(io.sized(`state|${cur.flow}:${cur.id}`, stateR(cur)) + 7, k);
      s._x = cur.x + Math.cos(t) * rr;
      s._y = cur.y + Math.sin(t) * rr;
      const hot = isHot("mtask", s), r = hot ? 4.5 : 2.8;
      cx.fillStyle = rgba(tierColor(s.model), 0.9);
      cx.beginPath();
      cx.arc(s._x, s._y, r, 0, TAU);
      cx.fill();
    }
  }
  function drawTasks() {
    for (const t of io.scene!.tasks) {
      if (t.gone) continue;
      const hot = isHot("task", t), r = t.big ? 4.2 : 2.6, lit = io.liveTasks.has(t.id);
      if (t.arrive) pulse(t.arrive.x, t.arrive.y, t.arrive.r || 10, t.arrive.age, t.arrive.col);
      if (t.moving && t.hop) {
        const c = t.hop.c;
        comet(c.p0, c.c, c.p1, t.hop.u, 3.2, tierColor(t.model)); // the head is drawn by the comet
        if (t.via) {
          const h = bez(c.p0, c.c, c.p1, t.hop.u);
          label(`${t.id} ${t.via}`, h.x, h.y - 16 / dc.K, false, null, 10.5);
        }
        continue;
      }
      if (t.big)
        for (let i = 0; i < 8; i++) {
          const a0 = t.ang - Math.sign(t.w) * 0.05 * (i + 1), a1 = t.ang - Math.sign(t.w) * 0.05 * i;
          cx.strokeStyle = rgba(tierColor(t.model), 0.34 * (1 - i / 8));
          cx.lineWidth = 2.2 * (1 - i / 10);
          cx.beginPath();
          cx.arc(t.host.x, t.host.y, t.R, Math.min(a0, a1), Math.max(a0, a1));
          cx.stroke();
        }
      dot(t.x, t.y, hot ? r * 1.7 : r, rgba(tierColor(t.model), hot || lit ? 1 : 0.8));
    }
  }
  // state level: each planet runs its own machine; every move is a comet along its chord and the planet's rim glows while it moves
  // what sits beside a moon (its DAGs, its name) clears its orbits and its ring; `past` is where its launch-only DAGs start, beyond its sub-states
  const clear = (p: Planet) => Math.max(p.rim ?? p.R, p.R + 5), past = (p: Planet) => clear(p) + (p.ext ?? 0) + 16;
  // the dashed stem from a moon (or the sub-state before it) out to a sub-state, edge to edge
  function stem(a: Planet, b: Planet, col: string, hot: boolean) {
    const u = Math.sign(b.x - a.x) || 1;
    cx.strokeStyle = rgba(col, hot ? 0.75 : 0.4);
    cx.lineWidth = 1 / dc.K ** 0.5;
    cx.setLineDash([2 / dc.K, 3 / dc.K]);
    cx.beginPath();
    cx.moveTo(a.x + u * (a.R + 3), a.y);
    cx.lineTo(b.x - u * (b.R + 3), b.y);
    cx.stroke();
    cx.setLineDash([]);
  }
  function drawPlanets() {
    const sc = io.scene!;
    for (const p of sc.planets) {
      const hot = isHot("planet", p), mv = p.pager ? p.pager.hidden.flatMap(io.moving) : io.moving(p.name);
      if (p.anchor) {
        cx.strokeStyle = rgba("#a78bfa", 0.4);
        cx.setLineDash([2, 4]);
        cx.lineWidth = 1;
        cx.beginPath();
        cx.moveTo(p.anchor.x, p.anchor.y + stateR(p.anchor) + 26);
        cx.lineTo(p.x, p.y - p.R - 18);
        cx.stroke();
        cx.setLineDash([]);
      }
      for (const R of p.rings || []) circle(p.x, p.y, R, rgba("#c4b5fd", 0.26), 1, [1.5, 4]); // the task orbits around this machine
      // a sub-state: a small fuchsia disc on a dashed stem from the body before it
      if (p.subState) {
        stem(p.prev!, p, "#e879f9", hot);
        disc(p.x, p.y, p.R, "#e879f9", hot, p.n ? 0.32 : 0.22);
        continue;
      }
      // a skill moon: a still disc, brighter while it has sessions and ringed in amber while one moves, named beside it away from the primary, past
      // the DAGs that orbit it; hover adds its states and sessions
      if (p.moon) {
        const sd = p.x < sc.hub!.x ? -1 : 1;
        const src = p.pager ? undefined : io.sourceOf(p.name);
        machine(p.x, p.y, p.R, hot, p.n ? 0.32 : 0.14, !!src);
        if (mv.length) circle(p.x, p.y, p.R + 4, rgba(ACT, 0.85), 1.5);
        cx.letterSpacing = `${0.5 / dc.K}px`;
        const col = rgba("#d8c8f5", hot ? 0.95 : 0.6);
        machineName(p.label || p.name, p.x + sd * past(p), p.y, labPx(11.5), col, sd < 0 ? "right" : "left", src);
        cx.letterSpacing = "0px";
        continue;
      }
      const psrc = io.sourceOf(p.name);
      dot(p.x, p.y, p.R + 14, "rgba(10,14,26,0.85)");
      if (mv.length) {
        const g = cx.createRadialGradient(p.x, p.y, p.R + 14, p.x, p.y, p.R + 30);
        g.addColorStop(0, rgba(ACT, 0.2));
        g.addColorStop(1, rgba(ACT, 0));
        cx.fillStyle = g;
        cx.beginPath();
        cx.arc(p.x, p.y, p.R + 30, 0, TAU);
        cx.arc(p.x, p.y, p.R + 14, 0, TAU, true);
        cx.fill();
      }
      circle(p.x, p.y, p.R + 14, mv.length ? rgba(ACT, 0.6) : rgba(psrc ? EXT : "#c084fc", hot ? 0.9 : psrc ? 0.6 : p.n ? 0.45 : 0.22), hot ? 2 : 1.2);
      drawMachineEdges(p.edges, true);
      drawStates(p.states, false);
      for (const e of mv) {
        const a = e.from ? p.states[e.from] : undefined, b = p.states[e.to];
        if (!a || !b || a === b) continue;
        const c = curveOf(a, b);
        comet(c.p0, c.c, c.p1, easeO((io.T - e.at) / TRAVEL), p.primary ? 3 : 2.4);
      }
      // a skill machine's name sits on its side facing away from the primary, so it never crosses the paths between them; the primary's goes below
      const nt = sc.tasks.filter((k) => k.host === p && !k.gone).length, size = p.primary ? 14 : 12;
      const sub = `${psrc ? `mapped from ${psrc} · ` : ""}${Object.keys(p.states).length} states${nt ? ` · ${nt} task${nt === 1 ? "" : "s"} orbiting` : ""} · ${p.n} task${p.n === 1 ? "" : "s"}${mv.length ? ` · ${mv.length} moving` : ""}`;
      let ux = 0, uy = 1;
      const hub = sc.hub;
      if (hub && p !== hub) {
        const dx = p.x - hub.x, dy = p.y - hub.y, L = Math.hypot(dx, dy) || 1;
        [ux, uy] = [dx / L, dy / L];
      }
      const off = Math.max(p.outer || 0, p.R + 14) + 20, hw = Math.max(textW(p.name, size), textW(sub, size - 2)) / 2;
      label(p.name, p.x + ux * (off + Math.abs(ux) * hw * 1.05), p.y + uy * off + (uy < 0 ? -16 : 0), hot, sub, size);
    }
  }
  function drawStars() {
    for (const grp of io.scene!.groups) {
      for (const s of grp.stars) {
        const live = !!s.active?.some((r) => r.status === "running"), status = live ? "running" : s.status;
        const col = DAG_COLOR[status] || "#94a3b8", hot = isHot("dag", s), g = s.glyph;
        if (hot || status === "running") {
          // no resting glow: only a hovered or currently running DAG gets a faint halo
          const glow = cx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.br * 1.3);
          glow.addColorStop(0, rgba(col, 0.09));
          glow.addColorStop(1, rgba(col, 0));
          cx.fillStyle = glow;
          cx.beginPath();
          cx.arc(s.x, s.y, s.br * 1.3, 0, TAU);
          cx.fill();
        }
        label(s.label, s.x, s.y + g.h / 2 + 16 / dc.K, hot, null, 11);
        // the DAG's own step graph in miniature: rounded links streaming toward the step that waits, ringed steps
        const nr = (g.nodes.length === 1 ? 5.5 : 4) * (hot ? 1.15 : 1);
        // a step's status: on a Ledger, the merge in focus's run; else from the runs in flight when there are any
        const folded = io.scene!.fold?.ledger && io.heldRows().length ? stepStates(io.focused(), s.name, g.nodes.map((n) => n.name)) ?? {} : null;
        const ss = (n: GNode) => (folded ? folded[n.name] ?? "not_started" : stepStatus(s, n.name, n.status));
        for (const [p, q] of g.links) {
          const a = { x: s.x + p.x, y: s.y + p.y, color: DAG_COLOR[ss(p)] || "#94a3b8" }, b = { x: s.x + q.x, y: s.y + q.y, color: DAG_COLOR[ss(q)] || "#94a3b8" };
          const running = ss(p) === "running" || ss(q) === "running", dx = (b.x - a.x) / 2;
          flowLine(a, b, hot || running ? 0.8 : 0.42, running ? 0.6 : 0, [1.5, 3.5]);
          cx.beginPath();
          cx.moveTo(a.x + nr, a.y);
          cx.bezierCurveTo(a.x + dx, a.y, b.x - dx, b.y, b.x - nr, b.y);
          cx.stroke();
          cx.setLineDash([]);
        }
        for (const n of g.nodes) {
          const st = ss(n), c = DAG_COLOR[st] || col, idle = st === "not_started", x = s.x + n.x, y = s.y + n.y;
          dot(x, y, nr, "rgba(6,10,20,0.9)");
          circle(x, y, nr, rgba(c, hot ? 1 : idle ? 0.45 : 0.85), hot ? 1.4 : 1);
          dot(x, y, nr * 0.34, rgba(c, idle ? 0.45 : 0.9));
          for (const r of io.moves.rings) if (r.dag === s.name && r.step === n.name) pulse(x, y, nr, (io.T - r.at) / RING, DAG_COLOR[r.status], 16); // a run entering or ending in this step rings it once
        }
        // the fan-out badge: the runs this DAG has running over its pool's cap, plus any waiting; red once the pool is full
        const fan = fanBadge(s, io.S?.pools);
        if (fan) {
          const bc = fan.full ? DAG_COLOR.failed : ACT, bw = textW(fan.text, 10.5) / dc.K + 6 / dc.K, bh = 15 / dc.K;
          const bx = s.x + g.w / 2 + nr + 8 / dc.K, by = s.y - g.h / 2 - nr - 10 / dc.K;
          cx.fillStyle = "rgba(6,10,20,0.85)";
          cx.strokeStyle = rgba(bc, 0.8);
          cx.lineWidth = 1 / dc.K;
          cx.beginPath();
          cx.roundRect(bx, by - bh / 2, bw, bh, bh / 2);
          cx.fill();
          cx.stroke();
          text(fan.text, bx + bw / 2, by + 0.5 / dc.K, 10.5 / dc.K, bc, "center", 500);
        }
        if (s.runnable) circle(s.x, s.y, s.br, rgba("#dbe4f3", 0.35), 1, [2, 3]);
        for (const age of dagRings(io.moves.flare[s.name], io.T)) pulse(s.x, s.y, s.br, age, ACT, 38); // each run ending rings its DAG
      }
    }
  }
  return { drawGalaxies, drawMoons, drawTies, drawBoardEdges, drawStateLinks, drawSun, drawPlanets, drawTasks, drawMachineEdges, drawStates, drawMachineTasks, drawStars };
}
