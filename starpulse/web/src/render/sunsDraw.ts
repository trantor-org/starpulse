// Paints the "B · Suns" drill-in board (features/level/sunsBoard.ts). Motion is the ledger's own: a comet for TRAVEL seconds when the task
// moves, then one PULSE ring where it lands, both in the task's colour (never the ACT amber their defaults carry). Streams march dashed like
// StarPulse's flow lines. Nothing but those streams moves until a transition is handed in, so a board that just loaded is still.
import type { Hit } from "../features/level/sunsHover";
import type { Flow, SunsBoard } from "../features/level/sunsBoard";
import { drawing, rgba, type DrawCtx } from "./draw";
import { curveOf } from "./scene";
import { PULSE, TRAVEL } from "./sky";

type Pt = { x: number; y: number };

/** One real transition of the task: it left `from` for `to` at `at` seconds on the same timeline as `now`. */
export interface Travel {
  from: Pt;
  to: Pt;
  at: number;
}
export interface View {
  now: number;
  travel?: Travel;
  hit?: Hit | null;
}

const TEXT = "#cbd5e1", SOFT = "#94a3b8", FLOW = "#3b82f6", LENS_JOIN = "#14b8a6", PILL_W = 28, PILL_H = 16, DOT_R = 4, SIZE = 11.5, ARC_PULL = 0.15;

export function drawSuns(dc: DrawCtx, b: SunsBoard, view: View) {
  const { cx } = dc, d = drawing(dc), { color } = b.task;
  const hot = (kind: Hit["kind"], id: string) => view.hit?.kind === kind && view.hit.id === id;

  // Group separators: lines between groups only, never between rows.
  for (const s of b.separators) {
    cx.strokeStyle = rgba(SOFT, 0.18);
    cx.lineWidth = 1;
    cx.beginPath();
    cx.moveTo(s.x0, s.y);
    cx.lineTo(s.x1, s.y);
    cx.stroke();
  }

  // The routing track and every stem into it: one track, one arc, in the phase and lens colours.
  const mid = (b.track.y0 + b.track.y1) / 2;
  d.flowLine({ x: b.track.x, y: b.track.y0, color: FLOW }, { x: b.track.x, y: b.track.y1, color: FLOW }, 0.5, 0, [2, 5]);
  cx.beginPath();
  cx.moveTo(b.track.x, b.track.y0);
  cx.lineTo(b.track.x, b.track.y1);
  cx.stroke();
  for (const st of b.stems) {
    const sun = b.suns.find((s) => s.id === st.row)!, [a, z] = st.points, dir = Math.sign(mid - a.y);
    d.flowLine({ ...a, color: sun.color }, { ...z, color: FLOW }, 0.5, 0, [2, 5]);
    cx.beginPath();
    cx.moveTo(a.x, a.y);
    cx.lineTo(z.x - (dir ? st.arc : 0), z.y);
    if (dir) cx.quadraticCurveTo(z.x, z.y, z.x, z.y + dir * st.arc);
    cx.stroke();
  }
  cx.setLineDash([]);

  // Entries and exits: a flat run at the edge, an S-curve that is flat at both ends into the board, a head on every exit.
  const stream = (f: Flow, from: Pt, to: Pt, c0: Pt, c1: Pt, tail: Pt, col: string) => {
    d.flowLine({ ...from, color: col }, { ...tail, color: col }, 0.55, 0, [2, 5]);
    cx.beginPath();
    cx.moveTo(from.x, from.y);
    cx.bezierCurveTo(c0.x, c0.y, c1.x, c1.y, to.x, to.y);
    cx.lineTo(tail.x, tail.y);
    cx.stroke();
    cx.setLineDash([]);
    d.text(f.label.text, f.label.x, f.label.y, SIZE, rgba(TEXT, 0.85), "left");
  };
  for (const f of b.entries) {
    const mx = (f.line.x1 + f.join.x) / 2;
    stream(f, { x: f.line.x0, y: f.line.y }, { x: f.join.x, y: f.join.y }, { x: f.line.x1, y: f.line.y }, { x: mx, y: f.join.y }, { x: f.join.x, y: f.join.y }, FLOW);
  }
  for (const f of b.exits) {
    const mx = (f.join.x + f.line.x0) / 2, end = { x: f.line.x1 - f.arrow, y: f.line.y };
    stream(f, f.join, { x: f.line.x0, y: f.line.y }, { x: mx, y: f.join.y }, { x: mx, y: f.line.y }, end, hot("exit", f.label.text) ? color : FLOW);
    d.arrow({ x: end.x - 1, y: end.y }, { x: f.line.x1, y: f.line.y }, rgba(FLOW, 0.8), f.arrow);
  }

  // Rows: sun, name above it, the one current state, round pills.
  for (const r of b.rows) {
    const sun = b.suns.find((s) => s.id === r.id)!, lit = hot("sun", r.id);
    cx.strokeStyle = rgba(sun.color, 0.12);
    cx.lineWidth = 1;
    cx.beginPath();
    cx.moveTo(sun.x + sun.r, r.y);
    cx.lineTo(b.track.x, r.y);
    cx.stroke();
    d.dot(sun.x, sun.y, sun.r, rgba(sun.color, lit ? 0.55 : 0.28));
    d.circle(sun.x, sun.y, sun.r, rgba(sun.color, lit ? 1 : 0.85), lit ? 2 : 1.4);
    d.text(sun.label.text, sun.label.x, sun.label.y, SIZE, rgba(TEXT, lit ? 1 : 0.75), "center");
    d.text(r.state, r.stateX, r.y, SIZE, rgba(TEXT, 0.9), "left");
    r.pills.forEach((p, i) => {
      const on = p.current, h = hot("pill", r.id) && view.hit?.kind === "pill" && view.hit.round === i + 1;
      cx.fillStyle = rgba(sun.color, on ? 0.3 : 0.06);
      cx.strokeStyle = rgba(sun.color, h || on ? 0.9 : 0.4);
      cx.lineWidth = 1;
      cx.beginPath();
      cx.roundRect(p.x - PILL_W / 2, p.y - PILL_H / 2, PILL_W, PILL_H, PILL_H / 2);
      cx.fill();
      cx.stroke();
      d.text(p.label, p.x, p.y, SIZE - 1.5, rgba(TEXT, on ? 1 : 0.6), "center");
    });
  }
  for (const f of b.dots) d.dot(f.x, f.y, 3, rgba(LENS_JOIN, 0.8));

  // The task: a comet while it travels, then one ring in its own colour, then a still dot.
  const t = view.travel, u = t ? (view.now - t.at) / TRAVEL : 9, pa = t ? (view.now - t.at - TRAVEL) / PULSE : 9;
  if (t && u >= 0 && u < 1) {
    const c = curveOf(t.from, t.to, ARC_PULL);
    d.comet(c.p0, c.c, c.p1, u, DOT_R, color);
    return;
  }
  const at = t && u < 0 ? t.from : b.task.at;
  if (t && pa >= 0 && pa < 1) d.pulse(at.x, at.y, DOT_R, pa, color, 18);
  d.dot(at.x, at.y, DOT_R, rgba(color, 0.95));
}
