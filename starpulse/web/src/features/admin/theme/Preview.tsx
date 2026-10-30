// The Admin's Preview card: a small Star Map and a Kanban card drawn at the chosen scale, density and motion in the theme's tokens, so a
// pack and a background are judged on the page's own shapes. The canvas reads the tokens at each frame; Motion off draws one still frame.
import { useEffect, useRef } from "react";
import { useViewActive } from "../../../shared/Kept";
import { labelPx } from "../adminPrefs";
import { easeO, rgba } from "../../../render/draw";
import { BUILTIN, SLATE, build } from "./scheme";

const TAU = Math.PI * 2, HOP = 2.4, REST = 1.1;
const FROM = { name: "In Progress", sub: "4 tasks", color: "agent" };
const TO = { name: "Review", sub: "2 tasks", color: "agent-hi" };
type Pt = { x: number; y: number };

const fallback = build(BUILTIN.starpulse, SLATE).t, PR = 2094;
/** A token as the page has it now, or the default theme's before one is applied. */
const token = (k: string) => getComputedStyle(document.documentElement).getPropertyValue(`--${k}`).trim() || fallback[k];

/**
 * Two Board states as suns with their names and counts, sized as the renderer sizes them, and a task hopping from one to the other as a
 * comet that lands with a pulse. `t` is seconds into the loop; with Motion off it is a still mid-hop.
 */
function drawPreview(c: HTMLCanvasElement, scale: number, t: number) {
  const r = c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  if (c.width !== Math.round(r.width * dpr) || c.height !== Math.round(r.height * dpr)) {
    c.width = Math.round(r.width * dpr);
    c.height = Math.round(r.height * dpr);
  }
  const cx = c.getContext("2d");
  if (!cx) return;
  const from = token(FROM.color), to = token(TO.color), act = token("run"), label = token("ink-2"), muted = token("slate");
  cx.setTransform(dpr, 0, 0, dpr, 0, 0);
  cx.clearRect(0, 0, r.width, r.height);
  const name = labelPx(12.5, 1, scale), sub = labelPx(10.5, 1, scale), R = Math.min(30, r.height / 5);
  const y = (r.height - name - sub - 9 + R * 0.1) / 2, gap = Math.min(r.width / 4, 220);
  const a: Pt = { x: r.width / 2 - gap, y }, b: Pt = { x: r.width / 2 + gap, y }, ctl: Pt = { x: r.width / 2, y: y - R * 2.2 };
  const sun = (p: Pt, col: string, hot: boolean) => {
    const g = cx.createRadialGradient(p.x, p.y, 0, p.x, p.y, R);
    g.addColorStop(0, rgba(col, 0.16));
    g.addColorStop(1, rgba(col, 0.02));
    cx.fillStyle = g;
    cx.beginPath();
    cx.arc(p.x, p.y, R, 0, TAU);
    cx.fill();
    cx.strokeStyle = rgba(col, hot ? 0.9 : 0.4);
    cx.lineWidth = hot ? 2 : 1.2;
    cx.stroke();
  };
  const caption = (p: Pt, s: typeof FROM, hot: boolean) => {
    cx.textAlign = "center";
    cx.textBaseline = "top";
    cx.letterSpacing = "0.6px";
    cx.font = `300 ${name}px Inter, system-ui, sans-serif`;
    cx.fillStyle = rgba(label, hot ? 0.95 : 0.58);
    cx.fillText(s.name, p.x, p.y + R + 6);
    cx.font = `300 ${sub}px Inter, system-ui, sans-serif`;
    cx.fillStyle = rgba(muted, hot ? 0.8 : 0.42);
    cx.fillText(s.sub, p.x, p.y + R + 9 + name);
    cx.letterSpacing = "0px";
  };
  const bez = (u: number): Pt => ({
    x: (1 - u) ** 2 * a.x + 2 * (1 - u) * u * ctl.x + u * u * b.x,
    y: (1 - u) ** 2 * a.y + 2 * (1 - u) * u * ctl.y + u * u * b.y,
  });
  // the flow between the two states, dashed as the map dashes it
  const flow = cx.createLinearGradient(a.x, a.y, b.x, b.y);
  flow.addColorStop(0, rgba(from, 0.35));
  flow.addColorStop(1, rgba(to, 0.35));
  cx.strokeStyle = flow;
  cx.lineWidth = 1;
  cx.setLineDash([2.4, 6]);
  cx.beginPath();
  cx.moveTo(a.x, a.y);
  cx.quadraticCurveTo(ctl.x, ctl.y, b.x, b.y);
  cx.stroke();
  cx.setLineDash([]);
  const phase = t % (HOP + REST), u = Math.min(1, phase / HOP), landed = phase >= HOP;
  sun(a, from, false);
  sun(b, to, landed);
  if (landed) {
    // the arrival pulse lights Review, under the labels so they stay readable
    const q = (phase - HOP) / REST;
    cx.strokeStyle = rgba(act, (1 - q) ** 2 * 0.85);
    cx.lineWidth = 2 * (1 - q) + 0.4;
    cx.beginPath();
    cx.arc(b.x, b.y, R + easeO(q) * 20, 0, TAU);
    cx.stroke();
  }
  caption(a, FROM, false);
  caption(b, TO, landed);
  if (landed) return;
  // the task as a comet: a tapering tail along the hop, then a glowing head
  const e = 1 - (1 - u) ** 2, n = 14, span = 0.27 * Math.min(1, e + 0.05);
  for (let i = 1; i <= n; i++) {
    const p = bez(Math.max(0, e - span * (1 - (i - 1) / n))), q = bez(Math.max(0, e - span * (1 - i / n)));
    cx.strokeStyle = rgba(act, (i / n) * 0.6);
    cx.lineWidth = (i / n) * 2.6;
    cx.beginPath();
    cx.moveTo(p.x, p.y);
    cx.lineTo(q.x, q.y);
    cx.stroke();
  }
  const h = bez(e);
  cx.globalCompositeOperation = "lighter";
  const glow = cx.createRadialGradient(h.x, h.y, 0, h.x, h.y, 14);
  glow.addColorStop(0, rgba(act, 0.7));
  glow.addColorStop(1, rgba(act, 0));
  cx.fillStyle = glow;
  cx.beginPath();
  cx.arc(h.x, h.y, 14, 0, TAU);
  cx.fill();
  cx.globalCompositeOperation = "source-over";
  cx.fillStyle = rgba(act, 0.95);
  cx.beginPath();
  cx.arc(h.x, h.y, 3, 0, TAU);
  cx.fill();
}

export function Preview({ scale, compact, motion }: { scale: number; compact: boolean; motion: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null), active = useViewActive();
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const t0 = performance.now();
    let raf = 0;
    const draw = () => drawPreview(c, scale, motion ? (performance.now() - t0) / 1000 : HOP * 0.55);
    const loop = () => {
      draw();
      raf = requestAnimationFrame(loop);
    };
    if (motion && active) loop();
    else draw();
    // the card's width also changes when the navigator folds, not only with the window; a theme change repaints the still
    const watch = new ResizeObserver(draw);
    watch.observe(c);
    window.addEventListener("sp:theme", draw);
    return () => {
      cancelAnimationFrame(raf);
      watch.disconnect();
      window.removeEventListener("sp:theme", draw);
    };
  }, [scale, motion, active]);
  return (
    <section className="card pvw">
      <h2>Preview</h2>
      <div className="pv">
        <div className="pvk">Star Map</div>
        <canvas ref={canvas} aria-label="A task moving from In Progress to Review" />
        <div className="pvk">Kanban card</div>
        <div className={compact ? "pvcard compact" : "pvcard"}>
          <div className="top"><span className="id">DEMO-101</span><span className="pr"><i />#{PR}</span></div>
          <div className="t">Sample card: how a title reads at this size</div>
          {!compact && <div className="foot2"><span className="lab">feature</span><span className="lab">size-3</span><span className="lab">adr-needed</span></div>}
          <button type="button" className="play edge" title="Start a session" aria-label="Start DEMO-101">▶</button>
        </div>
      </div>
    </section>
  );
}
