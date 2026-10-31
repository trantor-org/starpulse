// The In Progress drill-in: the approved "B · Suns" board (TASK-8665's mockup) of one task, the Tasks strip that picks it, and the replay of its
// last 24 hours (TASK-8664's /api/history). A region of the app shell opened by `?drill=TASK-N`, between the real Navigator and Rail, laid out from
// the region's measured size: no scaling, so its text keeps the size of every other view's.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createHistory } from "../../api/history";
import type { MachineEvent, Roles } from "../../api/types.gen";
import { ANIM_UNTIL, spanOf, starfield, type Line, type Scene } from "./sunsEngine";
import { css, jobOf, MOCKUP, sceneOf, type View } from "./sunsScene";
import { tint } from "./tint";

/** What the Tasks strip needs of a board card; a Kanban card has these and more. */
export interface DrillTask {
  id: string;
  title: string;
  lane: string;
  assignee?: string;
}

interface Props {
  tasks: DrillTask[];
  roles: Roles;
  /** The task shown first. */
  task: string;
  onClose: () => void;
  /** Epoch seconds; replaced in tests. */
  clock?: () => number;
}

/** The mockup's content starts at this x (the mockup's navigation was left of it) and its board at this y below the header, so the stage is offset by both. */
const ORIGIN = 251, TOP = 48;
/** Narrower or shorter than this the board scrolls rather than overlap: its phase columns need the room. */
const MIN_W = 800, MIN_H = 600;
const LANE = { stroke: tint("slate", 16) }, GUIDE = { stroke: tint("slate", 10) }, GROUP = { stroke: tint("released", 38) };
const SVG = { position: "absolute", left: 0, top: 0, pointerEvents: "none" } as const;

function Lines({ lines, w, h }: { lines: Line[]; w: number; h: number }) {
  return lines.map((l, i) => (
    <svg key={i} width={w} height={h} style={SVG} aria-hidden="true">
      <path d={l.d} fill="none" stroke={l.c} strokeWidth={l.w} strokeDasharray={l.dash} strokeLinecap={l.cap as "round"} strokeLinejoin="round" opacity={l.op} style={css(l.st)} />
    </svg>
  ));
}

/** The engine's glyphs, bodies, labels, badges and buttons, in the mockup's stacking order. */
function Pieces({ g }: { g: Scene }) {
  return (
    <>
      {g.S.map((s, i) => <span key={`s${i}`} style={css(s.style)} />)}
      {g.B.map((b, i) => <span key={`b${i}`} style={css(b.style)} />)}
      {g.T.map((t, i) => <span key={`t${i}`} style={css(t.style)}>{t.text}<span style={{ display: "block", fontSize: ".86em", color: t.subColor }}>{t.sub}</span></span>)}
      {g.K.map((k, i) => <span key={`k${i}`} style={css(k.style)}>{k.text}</span>)}
      {g.V.map((v, i) => <button key={`v${i}`} type="button" aria-label={v.aria} style={css(v.style)} onMouseEnter={v.enter} onMouseLeave={v.leave} onFocus={v.enter} onBlur={v.leave} onClick={v.pick} />)}
      {g.H.map((h, i) => <button key={`h${i}`} type="button" aria-label={h.aria} style={css(h.style)} onClick={h.pick} />)}
      {g.Q.map((q, i) => <button key={`q${i}`} type="button" aria-label={q.aria} style={css(q.style)} onClick={q.pick}>{q.text}</button>)}
    </>
  );
}

function Tip({ tip }: { tip: ReturnType<typeof sceneOf>["tip"] }) {
  return tip && (
    <div role="tooltip" style={css(tip.style)}>
      <div style={{ color: "var(--ink-hi)", marginBottom: 2 }}>{tip.t}</div>
      {tip.lines.map((s, i) => <div key={i} style={{ color: "var(--slate)" }}>{s}</div>)}
    </div>
  );
}

/** The size of `el`'s content box, kept current; 0 × 0 until it is laid out (jsdom never lays out). */
function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null), [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => setSize((s) => (s.w === el.clientWidth && s.h === el.clientHeight ? s : { w: el.clientWidth, h: el.clientHeight }));
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

export function SunsDrillIn({ tasks, roles, task, onClose, clock = () => Date.now() / 1000 }: Props) {
  const [view, setViewState] = useState<View>({ sel: task, open: {}, pick: {}, hover: null, det: null, at: null, replaying: false });
  const setView = useCallback((patch: Partial<View>) => setViewState((v) => ({ ...v, ...patch })), []);
  const [now, setNow] = useState(clock), [, redraw] = useState(0);
  const history = useMemo(() => createHistory({ onChange: () => redraw((n) => n + 1) }), []);
  const [body, room] = useSize<HTMLDivElement>();
  // the stage fills the room the shell leaves; before it is measured it is the mockup's own size
  const stageW = room.w ? Math.max(MIN_W, room.w) : MOCKUP.w, stageH = room.h ? Math.max(MIN_H, room.h) : MOCKUP.h - TOP;
  const size = { w: stageW, h: stageH + TOP }, W = ORIGIN + stageW, H = size.h;
  const stars = useMemo(() => starfield(W, H, 70), [W, H]);

  // the drilled task stands in by its id alone until the board's tasks arrive
  const working = tasks.filter((t) => t.lane === roles.working || t.id === task);
  const listed = working.some((t) => t.id === task) ? working : [{ id: task, title: "", lane: roles.working } as DrillTask, ...working];
  const events = new Map(listed.map((t): [string, MachineEvent[]] => {
    const e = history.replay(t.id);
    return [t.id, Array.isArray(e) ? e : []];
  }));
  const jobs = listed.map((t) => jobOf(t.id, t.title, t.assignee, events.get(t.id)!, now));
  const s = sceneOf(jobs, view, setView, now, size);

  const live = useRef({ view, job: s.job });
  useEffect(() => {
    live.current = { view, job: s.job };
  });
  useEffect(() => {
    // the scene's colours are read from the theme per draw, so a theme change only needs the next draw
    const repaint = () => redraw((n) => n + 1);
    window.addEventListener("sp:theme", repaint);
    return () => window.removeEventListener("sp:theme", repaint);
  }, []);
  useEffect(() => {
    // the replay steps back through the selected task's span in 240 ticks; the move animation redraws at 20 fps only while a comet flies
    const step = setInterval(() => {
      const { view: v, job } = live.current;
      if (!v.replaying || v.at == null) return;
      const at = v.at - spanOf(job) / 240;
      setView(at < 0.5 ? { at: null, replaying: false } : { at });
    }, 120);
    const anim = setInterval(() => ANIM_UNTIL > Date.now() && redraw((n) => n + 1), 50);
    const tick = setInterval(() => setNow(clock()), 60_000);
    const key = (e: KeyboardEvent) => e.key === "Escape" && (live.current.view.det ? setView({ det: null }) : onClose());
    addEventListener("keydown", key);
    return () => {
      [step, anim, tick].forEach(clearInterval);
      removeEventListener("keydown", key);
    };
  }, [clock, onClose, setView]);

  return (
    <section id="sd" role="dialog" aria-label="In Progress drill-in" className="suns-drill">
      <header>
        <button type="button" className="crumb" onClick={onClose} aria-label="Back to the Board">Board</button>
        {" "}<span className="sep">›</span>{" "}
        <span className="title">In Progress</span>
        <span className="count">{jobs.length} tasks · showing {s.job.id}</span>
        <nav aria-label="In Progress tasks" className="fleet">
          {s.fleet.map((f) => (
            <button key={f.id} type="button" className={f.on ? "fchip set" : "fchip"} aria-label={f.aria} aria-current={f.on} onClick={f.pick}>
              <b>{f.id}</b><span>{f.where}</span>
            </button>
          ))}
        </nav>
      </header>
      <div ref={body} className="sd-body">
        <div className="sd-stage" style={{ width: stageW, height: stageH }}>
          <div style={{ position: "absolute", left: -ORIGIN, top: -TOP, width: W, height: H, background: "radial-gradient(ellipse at 40% 30%, var(--bg1) 0%, var(--bg0) 70%)", color: "var(--ink)", fontSize: "calc(14px * var(--fs))" }}>
            {stars.map((st, i) => <span key={i} style={css(st.style)} />)}
            <svg width={W} height={H} style={SVG} aria-hidden="true">
              <path d={s.paths.lane} fill="none" style={LANE} strokeWidth={1} />
              <path d={s.paths.guide} fill="none" style={GUIDE} strokeWidth={1} strokeDasharray="1 5" />
              <path d={s.paths.grp} fill="none" style={GROUP} strokeWidth={1} />
            </svg>
            <Lines lines={s.main.L} w={W} h={H} />
            <Pieces g={s.main} />
            <div style={{ position: "absolute", left: ORIGIN, top: 393, width: stageW, height: s.rowsViewH, overflowY: "auto", overflowX: "hidden", scrollbarWidth: "thin", scrollbarColor: `${tint("slate", 25)} transparent` }}>
              <div style={{ position: "relative", left: -ORIGIN, top: s.rowsTop, width: W, height: s.rowsH, marginBottom: s.rowsTop }}>
                <svg width={W} height={s.rowsH} style={SVG} aria-hidden="true">
                  <path d={s.rpaths.lane} fill="none" style={LANE} strokeWidth={1} />
                  <path d={s.rpaths.grp} fill="none" style={GROUP} strokeWidth={1} />
                </svg>
                <Lines lines={s.rows.L} w={W} h={s.rowsH} />
                <Pieces g={s.rows} />
                <Tip tip={s.rtip} />
              </div>
            </div>
            <Tip tip={s.tip} />
          </div>
          {s.det && (
            <section aria-label="Details" className="sd-details">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <span style={{ letterSpacing: ".22em", color: "var(--muted)", fontSize: ".9em" }}>DETAILS</span>
                <button type="button" aria-label="Close details" onClick={() => setView({ det: null })} style={{ all: "unset", cursor: "pointer", color: "var(--slate)", fontSize: "1.2em", lineHeight: 1, padding: "0 4px" }}>×</button>
              </div>
              <div style={{ marginTop: 14, color: "var(--ink-hi)", fontSize: "1.15em" }}>{s.det.title}</div>
              <div style={{ marginTop: 4, color: "var(--slate)" }}>{s.det.sub}</div>
              <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 10 }}>
                {s.det.rows.map((r, i) => (
                  <div key={i}>
                    <div style={{ color: "var(--muted)", fontSize: ".86em", letterSpacing: ".06em" }}>{r.k}</div>
                    <div style={{ color: r.c ?? "var(--ink)", marginTop: 2, lineHeight: 1.45 }}>{r.v}</div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </section>
  );
}
