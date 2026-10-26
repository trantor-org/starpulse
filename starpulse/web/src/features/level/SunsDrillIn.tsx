// The In Progress drill-in: the approved "B · Suns" board (TASK-8665's mockup) of one task, the Tasks panel that picks it, and the replay of its
// last 24 hours (TASK-8664's /api/history). A fixed overlay opened by `?drill=TASK-N`, drawn at the mockup's 1440×900 and scaled to the window.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createHistory } from "../../api/history";
import type { MachineEvent, Roles } from "../../api/types.gen";
import { ANIM_UNTIL, spanOf, starfield, type Line, type Scene } from "./sunsEngine";
import { css, jobOf, sceneOf, type View } from "./sunsScene";

/** What the Tasks panel needs of a board card; a Kanban card has these and more. */
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
  /** The DAGs view's count. */
  dags?: number;
  /** Epoch seconds; replaced in tests. */
  clock?: () => number;
}

const W = 1440, H = 900, RECENT = 14;
const SVG = { position: "absolute", left: 0, top: 0, pointerEvents: "none" } as const;
const PANEL = { position: "absolute", top: 0, bottom: 0, width: 250, background: "rgba(5,7,13,.55)", padding: "20px 18px", boxSizing: "border-box" } as const;
const HEAD = { letterSpacing: ".22em", fontSize: ".78em", color: "#6b7a93" } as const;
const NAV = { display: "flex", alignItems: "center", gap: 12, padding: "6px 18px", marginLeft: -18 } as const;
const fit = () => Math.min(window.innerWidth / W, window.innerHeight / H);
const clockText = (sec: number) => new Date(sec * 1000).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZoneName: "short" });
const hm = (sec: number) => new Date(sec * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });

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
      <div style={{ color: "#f1f5f9", marginBottom: 2 }}>{tip.t}</div>
      {tip.lines.map((s, i) => <div key={i} style={{ color: "#94a3b8" }}>{s}</div>)}
    </div>
  );
}

export function SunsDrillIn({ tasks, roles, task, onClose, dags, clock = () => Date.now() / 1000 }: Props) {
  const [view, setViewState] = useState<View>({ sel: task, open: {}, pick: {}, hover: null, det: null, at: null, replaying: false });
  const setView = useCallback((patch: Partial<View>) => setViewState((v) => ({ ...v, ...patch })), []);
  const [now, setNow] = useState(clock), [scale, setScale] = useState(fit), [, redraw] = useState(0);
  const history = useMemo(() => createHistory({ onChange: () => redraw((n) => n + 1) }), []);
  const stars = useMemo(() => starfield(W, H, 70), []);

  // the drilled task stands in by its id alone until the board's tasks arrive
  const working = tasks.filter((t) => t.lane === roles.working || t.id === task);
  const listed = working.some((t) => t.id === task) ? working : [{ id: task, title: "", lane: roles.working } as DrillTask, ...working];
  const events = new Map(listed.map((t): [string, MachineEvent[]] => {
    const e = history.replay(t.id);
    return [t.id, Array.isArray(e) ? e : []];
  }));
  const jobs = listed.map((t) => jobOf(t.id, t.title, t.assignee, events.get(t.id)!, now));
  const s = sceneOf(jobs, view, setView, now);
  const recent = [...events].flatMap(([id, es]) => es.filter((e) => e.from !== e.to).map((e) => ({ at: e.at, text: `${id} · ${e.machine} ${e.to}` })))
    .sort((a, b) => b.at - a.at).slice(0, RECENT);

  const live = useRef({ view, job: s.job });
  useEffect(() => {
    live.current = { view, job: s.job };
  });
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
    const resize = () => setScale(fit());
    const key = (e: KeyboardEvent) => e.key === "Escape" && (live.current.view.det ? setView({ det: null }) : onClose());
    addEventListener("resize", resize);
    addEventListener("keydown", key);
    return () => {
      [step, anim, tick].forEach(clearInterval);
      removeEventListener("resize", resize);
      removeEventListener("keydown", key);
    };
  }, [clock, onClose, setView]);

  return (
    <div role="dialog" aria-label="In Progress drill-in" className="suns-drill" style={{ position: "fixed", inset: 0, zIndex: 50, overflow: "hidden", background: "#05070d" }}>
      <div style={{ position: "absolute", left: "50%", top: "50%", width: W, height: H, transform: `translate(-50%,-50%) scale(${scale})`, boxSizing: "border-box", background: "#05070d", color: "#dbe4f3", fontFamily: "Inter,system-ui,sans-serif", fontSize: "calc(14px * var(--fs))", overflow: "hidden" }}>
        <div style={{ position: "relative", width: W, height: H, overflow: "hidden", background: "radial-gradient(ellipse at 40% 30%, #0b1224 0%, #05070d 70%)" }}>
          {stars.map((st, i) => <span key={i} style={css(st.style)} />)}
          <nav aria-label="Tasks" style={{ ...PANEL, left: 0, borderRight: "1px solid rgba(148,163,184,.08)", fontSize: ".86em" }}>
            <div style={{ letterSpacing: ".32em", fontSize: "1.05em", color: "#e2e8f0" }}>STARPULSE</div>
            <div style={{ marginTop: 8, color: "#94a3b8", fontSize: ".86em" }}>
              <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "#34d399", marginRight: 6 }} />live · {clockText(now)}
            </div>
            <div style={{ ...HEAD, margin: "28px 0 8px" }}>VIEWS</div>
            <div style={{ ...NAV, background: "linear-gradient(90deg,rgba(167,139,250,.16),transparent)", borderLeft: "2px solid #a78bfa" }}>
              <span style={{ width: 12, height: 12, borderRadius: 3, border: "1px solid #c4b5fd" }} /><span style={{ flex: 1, color: "#e2e8f0" }}>Star Map</span>
            </div>
            <div style={NAV}>
              <span style={{ width: 12, height: 12, borderRadius: 3, border: "1px solid #64748b" }} /><span style={{ flex: 1, color: "#cbd5e1" }}>Kanban</span><span style={{ color: "#6b7a93", fontSize: ".86em" }}>{tasks.length}</span>
            </div>
            <div style={NAV}>
              <span style={{ width: 12, height: 12, borderRadius: 3, border: "1px solid #64748b" }} /><span style={{ flex: 1, color: "#cbd5e1" }}>DAGs</span><span style={{ color: "#6b7a93", fontSize: ".86em" }}>{dags || ""}</span>
            </div>
            <div style={{ marginTop: 22, border: "1px solid rgba(148,163,184,.18)", borderRadius: 6, padding: "6px 10px", color: "#64748b" }}>search…</div>
            <div style={{ ...HEAD, margin: "30px 0 10px", display: "flex", justifyContent: "space-between" }}><span>TASKS</span></div>
            <div style={{ display: "flex", justifyContent: "space-between", color: "#94a3b8", fontSize: ".86em", marginBottom: 4 }}><span>In Progress</span><span>{jobs.length}</span></div>
            {s.fleet.map((f) => (
              <button key={f.id} type="button" aria-label={f.aria} aria-current={f.on} onClick={f.pick}
                style={{ all: "unset", cursor: "pointer", display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "baseline", width: "100%", boxSizing: "border-box", padding: "5px 6px", margin: "0 -6px", borderRadius: 4, background: f.on ? "rgba(167,139,250,.12)" : undefined }}>
                <span style={{ fontFamily: "JetBrains Mono,monospace", fontSize: ".95em", color: f.on ? "#ede9fe" : "#dbe4f3" }}>{f.id}</span>
                <span style={{ color: "#6b7a93", fontSize: ".86em" }}>{f.where}</span>
                <span style={css(f.bar)} />
              </button>
            ))}
          </nav>
          <section aria-label="Recent" style={{ ...PANEL, right: 0, borderLeft: "1px solid rgba(148,163,184,.08)", fontSize: ".8em" }}>
            <div style={{ letterSpacing: ".22em", color: "#6b7a93", marginBottom: 10, fontSize: ".9em" }}>RECENT</div>
            {recent.map((r, i) => (
              <div key={i} style={{ fontFamily: "JetBrains Mono, monospace", color: "#cbd5e1", padding: "2px 0", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                <span style={{ color: "#475569", marginRight: 8 }}>{hm(r.at)}</span>{r.text}
              </div>
            ))}
            {s.det && (
              <section aria-label="Details" style={{ position: "absolute", inset: 0, background: "#070b16", padding: "20px 18px", boxSizing: "border-box" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <span style={{ letterSpacing: ".22em", color: "#6b7a93", fontSize: ".9em" }}>DETAILS</span>
                  <button type="button" aria-label="Close details" onClick={() => setView({ det: null })} style={{ all: "unset", cursor: "pointer", color: "#94a3b8", fontSize: "1.2em", lineHeight: 1, padding: "0 4px" }}>×</button>
                </div>
                <div style={{ marginTop: 14, color: "#f1f5f9", fontSize: "1.15em" }}>{s.det.title}</div>
                <div style={{ marginTop: 4, color: "#94a3b8" }}>{s.det.sub}</div>
                <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 10 }}>
                  {s.det.rows.map((r, i) => (
                    <div key={i}>
                      <div style={{ color: "#6b7a93", fontSize: ".86em", letterSpacing: ".06em" }}>{r.k}</div>
                      <div style={{ color: r.c ?? "#dbe4f3", marginTop: 2, lineHeight: 1.45 }}>{r.v}</div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </section>
          <svg width={W} height={H} style={SVG} aria-hidden="true">
            <path d={s.paths.lane} fill="none" stroke="rgba(148,163,184,.16)" strokeWidth={1} />
            <path d={s.paths.guide} fill="none" stroke="rgba(148,163,184,.10)" strokeWidth={1} strokeDasharray="1 5" />
            <path d={s.paths.grp} fill="none" stroke="rgba(94,234,212,.38)" strokeWidth={1} />
          </svg>
          <Lines lines={s.main.L} w={W} h={H} />
          <Pieces g={s.main} />
          <div style={{ position: "absolute", left: 251, top: 393, width: 939, height: 437, overflowY: "auto", overflowX: "hidden", scrollbarWidth: "thin", scrollbarColor: "rgba(148,163,184,.25) transparent" }}>
            <div style={{ position: "relative", left: -251, top: s.rowsTop, width: 1190, height: s.rowsH, marginBottom: s.rowsTop }}>
              <svg width={1190} height={s.rowsH} style={SVG} aria-hidden="true">
                <path d={s.rpaths.lane} fill="none" stroke="rgba(148,163,184,.16)" strokeWidth={1} />
                <path d={s.rpaths.grp} fill="none" stroke="rgba(94,234,212,.38)" strokeWidth={1} />
              </svg>
              <Lines lines={s.rows.L} w={1190} h={s.rowsH} />
              <Pieces g={s.rows} />
              <Tip tip={s.rtip} />
            </div>
          </div>
          <Tip tip={s.tip} />
          <div style={{ position: "absolute", left: 274, top: 16, display: "flex", flexDirection: "column", gap: 9 }}>
            <span style={{ fontSize: ".86em", color: "#94a3b8" }}>
              <button type="button" onClick={onClose} aria-label="Back to the Board" style={{ all: "unset", cursor: "pointer" }}>Board</button> <span style={{ color: "#475569" }}>›</span> <span style={{ color: "#e2e8f0" }}>In Progress</span>
            </span>
            <span style={{ fontSize: ".93em", color: "#dbe4f3", letterSpacing: ".05em" }}>in-progress</span>
            <span style={{ fontSize: ".72em", color: "#6b7a93", letterSpacing: ".04em" }}>{jobs.length} tasks · showing {s.job.id}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
