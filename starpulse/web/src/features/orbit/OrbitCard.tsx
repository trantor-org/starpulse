// The level above the Board, drawn as the approved orbit card: its own canvas (`orbitDraw`), the sign-in gate when the level
// refuses the session, and the drift badge over it.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Drift } from "./orbit";
import { layoutOrbit } from "./orbit";
import { arrivalDays, describeHover, drawOrbit, hitOrbit, type Hover } from "./orbitDraw";
import { focusDetails, type Details } from "./orbitDetails";
import { clickFocus, focusKey, focusOrder, refocus } from "./orbitFocus";
import { orbitInput, type LevelResponse, type LevelState } from "./levelData";
import { fitLevel, toWorld, wheelFactor, zoomAbout, type View } from "../../render/zoom";

const DAY = 86400;

/** What the level answers an expired or refused session: the sign-in link and, for a refusal, why. */
export function Gate({ why, reason }: { why: "expired" | "refused"; reason?: string }) {
  return (
    <div className="og-gate" role="alert">
      <h2>{why === "expired" ? "Your session ended" : "This account can't read the level"}</h2>
      <p>{why === "expired" ? "Sign in again to see how your runs flow." : reason || "The level is limited to the people its team names."}</p>
      <a className="og-btn" href="/auth/login">{why === "expired" ? "Sign in" : "Sign in as someone else"}</a>
    </div>
  );
}

/** The sources whose runs report states the level's config does not list, or stopped reporting ones it does. */
export function DriftBadge({ sources }: { sources: { name: string; drift?: Drift }[] }) {
  const drifted = sources.filter((s) => s.drift && (s.drift.added.length || s.drift.removed.length));
  if (!drifted.length) return null;
  return (
    <div className="og-drift" title="The states these sources report differ from the level's config">
      <b>Source drift</b>
      {drifted.map((s) => (
        <span key={s.name}>
          {s.name} {s.drift!.added.map((a) => <i key={`+${a}`} className="add">+{a}</i>)} {s.drift!.removed.map((r) => <i key={`-${r}`} className="del">−{r}</i>)}
        </span>
      ))}
    </div>
  );
}

/** The level above the Board, or what stands in its place: a note while it loads, the gate, or the failure. */
export function OrbitCard({ state, retry, motion, names = {} }: { state: LevelState; retry: () => void; motion: boolean; names?: Record<string, string> }) {
  if (state.kind === "gate") return <section id="og"><Gate why={state.why} reason={state.reason} /></section>;
  if (state.kind === "error") return <section id="og"><div className="og-gate"><h2>The level isn't available</h2><p>{state.message}</p><button className="og-btn" onClick={retry}>Retry</button></div></section>;
  if (state.kind !== "ok") return <section id="og"><p className="og-none centre">{state.kind === "loading" ? "Reading the level…" : "This server has no level."}</p></section>;
  return <section id="og"><Orbit level={state.level} motion={motion} names={names} /></section>;
}

function Orbit({ level, motion, names }: { level: LevelResponse; motion: boolean; names: Record<string, string> }) {
  const canvas = useRef<HTMLCanvasElement>(null), box = useRef<HTMLDivElement>(null), tipEl = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  // the body under the pointer, for the tip that follows it, and the focused body, for the details panel
  const [tip, setTip] = useState<Hover | null>(null), [picked, setPicked] = useState<Hover | null>(null);
  const tipAt = useRef({ left: 0, top: 0 });
  const days = Math.round(level.window_s / DAY);
  const aspect = size.w > 0 && size.h > 0 ? size.w / size.h : 1.6;
  const input = useMemo(() => orbitInput(level, (id) => names[id] ?? id.replace(/_/g, " "), aspect), [level, aspect, names]);
  const scene = useMemo(() => layoutOrbit(input), [input]);
  const arrivals = useMemo(() => arrivalDays(level.arrivals, level.now, level.window_s), [level]);
  const live = useRef({ scene, input, arrivals, level, days, motion });
  const view = useRef<View | null>(null), hover = useRef<Hover | null>(null), focus = useRef<Hover | null>(null), offsets = useRef(new Map<string, number>()), paint = useRef<(now?: number) => void>(() => {});

  // the tip's corner beside a screen point, kept inside the card; it reads and writes refs only, so every closure can share it
  const placeTip = (x: number, y: number, w: number, h: number) => {
    tipAt.current = { left: Math.max(8, Math.min(x + 16, w - 280)), top: Math.min(y + 16, h - 120) };
    if (tipEl.current) Object.assign(tipEl.current.style, { left: `${tipAt.current.left}px`, top: `${tipAt.current.top}px` });
  };
  // a tip that has just appeared stands where the last pointer move or frame put it
  const showTip = (el: HTMLDivElement | null) => {
    tipEl.current = el;
    if (el) Object.assign(el.style, { left: `${tipAt.current.left}px`, top: `${tipAt.current.top}px` });
  };
  // a click, Tab or the panel's close sets the focus; it reads and writes refs and setters only, so every closure can share it
  const choose = (f: Hover | null) => {
    focus.current = f;
    setPicked(f);
    if (!live.current.motion) paint.current();
  };

  // what the draw and the pointer handlers read; declared first so it is current before either runs
  useEffect(() => {
    live.current = { scene, input, arrivals, level, days, motion };
  });

  // a new snapshot lays the bodies out afresh: keep the focus on the same body, or drop it when the body is gone (the
  // tip and the panel find their bodies again the same way as they render)
  useEffect(() => {
    hover.current = null;
    focus.current = refocus(scene, focus.current);
  }, [scene]);

  useEffect(() => {
    const el = box.current!;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cv = canvas.current!;
    let raf = 0, t0 = -1;
    paint.current = (now = Date.now()) => {
      if (t0 < 0) t0 = now;
      const cx = cv.getContext("2d"), L = live.current;
      if (!cx || !size.w || !size.h) return;
      const dpr = window.devicePixelRatio || 1;
      if (cv.width !== Math.round(size.w * dpr) || cv.height !== Math.round(size.h * dpr)) {
        cv.width = Math.round(size.w * dpr);
        cv.height = Math.round(size.h * dpr);
      }
      if (!L.motion) offsets.current.clear(); // a still frame has no motion to ease the label offsets over
      const fit = fitLevel(L.scene, size.w, size.h), v = view.current ?? fit;
      // where the centre and the terminal suns stand on screen, for the window-size checks
      const at = (o: { x: number; y: number; r?: number }) => [o.x * v.k + v.x, o.y * v.k + v.y, (o.r ?? 0) * v.k].map(Math.round).join(",");
      cv.dataset.centre = at(L.scene.c);
      cv.dataset.ends = L.scene.ends.map(at).join(";");
      cx.setTransform(1, 0, 0, 1, 0, 0);
      cx.clearRect(0, 0, cv.width, cv.height);
      cx.setTransform(dpr * v.k, 0, 0, dpr * v.k, dpr * v.x, dpr * v.y);
      drawOrbit(cx, {
        scene: L.scene, input: L.input, k: v.k, zs: v.k / fit.k, clock: L.motion ? (now - t0) / 1000 : 10, hover: hover.current, focus: focus.current,
        measure: L.level.level.activity.measure, pace: L.level.level.activity.pace, days: L.days, arrivals: L.arrivals, offsets: offsets.current,
      });
    };
    const frame = (ts: number) => {
      paint.current(ts);
      raf = requestAnimationFrame(frame);
    };
    if (motion) raf = requestAnimationFrame(frame);
    else paint.current();
    return () => cancelAnimationFrame(raf);
  }, [size, scene, motion]);

  // the wheel zooms about the cursor and the drag pans, as on the Star Map; a still click focuses a body and one on empty space
  // clears it, Tab steps through the bodies and Esc clears; a second click or Enter on the focused body is held for drilling in
  useEffect(() => {
    const cv = canvas.current!;
    const fitNow = () => fitLevel(live.current.scene, cv.clientWidth, cv.clientHeight);
    const at = (e: { clientX: number; clientY: number }) => {
      const r = cv.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const hitAt = (p: { x: number; y: number }) => {
      const w = toWorld(view.current ?? fitNow(), p);
      return hitOrbit(live.current.scene, w.x, w.y);
    };
    let drag: { x: number; y: number; v: View; moved: boolean } | null = null;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const fit = fitNow();
      view.current = zoomAbout(view.current ?? fit, fit, at(e), wheelFactor(e.deltaY, e.deltaMode, cv.clientHeight));
      if (!live.current.motion) paint.current();
    };
    const down = (e: PointerEvent) => {
      const fit = fitNow();
      drag = { ...at(e), v: view.current ?? fit, moved: false };
      cv.setPointerCapture(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      const p = at(e), fit = fitNow();
      if (drag) {
        const dx = p.x - drag.x, dy = p.y - drag.y;
        if (Math.hypot(dx, dy) > 4) drag.moved = true;
        if (drag.moved && drag.v.k > fit.k * 1.001) view.current = { ...drag.v, x: drag.v.x + dx, y: drag.v.y + dy };
      }
      const h = hitAt(p);
      hover.current = h;
      cv.style.cursor = drag?.moved ? "grabbing" : h ? "pointer" : "default";
      if (h) placeTip(p.x, p.y, cv.clientWidth, cv.clientHeight);
      setTip(h);
      if (!live.current.motion) paint.current();
    };
    const up = (e: PointerEvent) => {
      const was = drag;
      drag = null;
      if (!was || was.moved) return;
      choose(clickFocus(focus.current, hitAt(at(e))));
    };
    const leave = () => {
      hover.current = null;
      setTip(null);
      if (!live.current.motion) paint.current();
    };
    const key = (e: KeyboardEvent) => {
      const r = focusKey(focusOrder(live.current.scene), focus.current, e.key, e.shiftKey);
      if (r.handled) {
        e.preventDefault();
        e.stopPropagation();
      }
      if (r.focus !== focus.current) choose(r.focus);
    };
    cv.addEventListener("wheel", wheel, { passive: false });
    cv.addEventListener("pointerdown", down);
    cv.addEventListener("pointermove", move);
    cv.addEventListener("pointerup", up);
    cv.addEventListener("pointerleave", leave);
    cv.addEventListener("keydown", key);
    return () => {
      cv.removeEventListener("wheel", wheel);
      cv.removeEventListener("pointerdown", down);
      cv.removeEventListener("pointermove", move);
      cv.removeEventListener("pointerup", up);
      cv.removeEventListener("pointerleave", leave);
      cv.removeEventListener("keydown", key);
    };
  }, []);

  // a canvas that changed shape refits unless the operator zoomed in
  useEffect(() => {
    const fit = fitLevel(scene, size.w || 1, size.h || 1);
    if (view.current && view.current.k <= fit.k * 1.02) view.current = null;
  }, [scene, size]);

  const ended = Object.values(level.orbit.terminals).reduce((a, t) => a + t.ended, 0);
  const hovered = refocus(scene, tip), shown = refocus(scene, picked);
  const tipText = hovered ? describeHover(hovered, { scene, input, days }) : null;
  const details = shown ? focusDetails(shown, level, scene, input.name) : null;
  return (
    <div ref={box} className={details ? "og-box picked" : "og-box"} data-suns={level.level.orbit.suns}>
      <canvas ref={canvas} tabIndex={0} aria-describedby={tipText ? "og-tip" : undefined} aria-label={`${level.level.title}: ${level.sources.length} sources orbiting ${scene.suns.length} suns`} />
      <header className="og-head">
        <h2>{level.level.title}</h2>
        <span>last {days} days · {ended} {level.level.runs} ended · {level.wip.count} open · suns are {level.level.orbit.suns === "working" ? "where runs spend their time" : "where runs end"}</span>
        <DriftBadge sources={level.sources.map((s) => ({ name: s.id, drift: s.drift }))} />
      </header>
      {tipText && (
        <div ref={showTip} id="og-tip" className="og-tip">
          <div className="k">{tipText.kind}</div>
          <div className="n">{tipText.name}</div>
          {tipText.lines.map((l) => <div key={l}>{l}</div>)}
          <div>{tipText.chips.map((c) => <span key={c.text} className="chip-line"><span style={{ color: c.col }}>●</span> {c.text}</span>)}</div>
        </div>
      )}
      {details && <DetailsPanel details={details} close={() => choose(null)} />}
    </div>
  );
}

/** The focused body's details, docked in the card: what the tip says and more, until Esc, ✕ or a click on empty space. */
export function DetailsPanel({ details, close }: { details: Details; close: () => void }) {
  return (
    <aside className="og-panel" aria-label={`${details.name} details`} onKeyDown={(e) => e.key === "Escape" && close()}>
      <button className="x" aria-label="Close details" onClick={close}>✕</button>
      <div className="k">{details.kind}</div>
      <h3>{details.name}</h3>
      <table><tbody>{details.facts.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody></table>
      {details.sections.map((s) => (
        <section key={s.title}>
          <h4>{s.title}</h4>
          {s.rows.map((r, i) => (
            <div key={i} className={r.warn ? "row warn" : "row"}>
              <span>{r.col && <i style={{ background: r.col }} />}{r.label}</span>
              <span>{r.value}{r.warn && " · aging"}</span>
            </div>
          ))}
          {s.more > 0 && <div className="more">+{s.more} more</div>}
        </section>
      ))}
    </aside>
  );
}
