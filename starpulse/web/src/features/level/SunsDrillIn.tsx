// The In Progress drill-in: the "B · Suns" board of one task, the Tasks panel that picks it, and the scrubber that replays its last 24 hours
// (TASK-8664's /api/history). A fixed overlay opened by `?drill=TASK-N`; the board holds still until a real transition crosses the shown time.
import { useEffect, useMemo, useRef, useState } from "react";
import { createHistory } from "../../api/history";
import type { Roles } from "../../api/types.gen";
import { PULSE, TRAVEL } from "../../render/sky";
import { drawSuns, type Travel } from "../../render/sunsDraw";
import { drillBoard } from "./sunsDrill";
import { detailsOf, hitAt, type Details, type Hit } from "./sunsHover";
import { goLive, pause, play, replayStep, scrubTo, startReplay, WINDOW, type MachineEvent } from "./sunsReplay";

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
  /** Epoch seconds; replaced in tests. */
  clock?: () => number;
}

const NO_EVENTS: MachineEvent[] = [];
const PANEL = { width: 220, borderRight: "1px solid #1e293b", padding: 12, overflow: "auto" } as const;

export function SunsDrillIn({ tasks, roles, task, onClose, clock = () => Date.now() / 1000 }: Props) {
  const working = useMemo(() => tasks.filter((t) => t.lane === roles.working), [tasks, roles.working]);
  const [id, setId] = useState(task), [, redraw] = useState(0);
  const [replay, setReplay] = useState(() => startReplay(clock()));
  const [hit, setHit] = useState<Hit | null>(null), [tip, setTip] = useState<Details | null>(null), [data, setData] = useState<Details | null>(null);
  const history = useMemo(() => createHistory({ onChange: () => redraw((n) => n + 1) }), []);
  const events = history.replay(id), list = Array.isArray(events) ? events : NO_EVENTS;
  const pick = tasks.find((t) => t.id === id);

  const canvas = useRef<HTMLCanvasElement>(null), live = useRef({ replay, list, id, profile: pick?.assignee, hit });
  useEffect(() => {
    live.current = { replay, list, id, profile: pick?.assignee, hit };
  });
  const shown = useRef<{ board: ReturnType<typeof drillBoard>["board"] | null }>({ board: null });

  useEffect(() => {
    let raf = 0, last = -1, prevT = clock(), hop: { travel: Travel; start: number } | null = null, current = live.current.replay;
    const frame = () => {
      const page = performance.now() / 1000, dt = last < 0 ? 0 : page - last, now = clock(), l = live.current;
      last = page;
      const next = replayStep(current === l.replay ? l.replay : current, dt, now);
      if (next !== l.replay) setReplay(next);
      current = next;
      const t = next.live ? now : next.t;
      const d = drillBoard({ id: l.id, profile: l.profile }, l.list, t, prevT);
      if (d.travel) hop = { travel: d.travel, start: page };
      if (hop && page - hop.start > TRAVEL + PULSE) hop = null;
      prevT = t;
      shown.current.board = d.board;
      const el = canvas.current, cx = el?.getContext("2d");
      if (el && cx) {
        const dpr = window.devicePixelRatio || 1;
        el.width = d.board.width * dpr;
        el.height = d.board.height * dpr;
        cx.setTransform(dpr, 0, 0, dpr, 0, 0);
        drawSuns({ cx, K: 1, ZS: 1, clock: page, scale: 1, hover: null }, d.board, { now: page, travel: hop ? { ...hop.travel, at: hop.start } : undefined, hit: l.hit });
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [clock]);

  const at = (e: React.MouseEvent<HTMLCanvasElement>): [Hit | null, Details | null] => {
    const b = shown.current.board, r = e.currentTarget.getBoundingClientRect();
    const h = b && r.width ? hitAt(b, ((e.clientX - r.left) / r.width) * b.width, ((e.clientY - r.top) / r.height) * b.height) : null;
    return [h, h && b ? detailsOf(b, h, list) : null];
  };
  const now = clock(), ago = replay.live ? 0 : Math.round(now - replay.t);

  return (
    <div role="dialog" aria-label="In Progress drill-in" style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", background: "#0b1020", color: "#cbd5e1", font: "13px system-ui" }}>
      <nav aria-label="Tasks" style={PANEL}>
        <h3 style={{ margin: "0 0 8px", font: "600 13px system-ui" }}>Tasks</h3>
        {working.map((t) => (
          <button key={t.id} type="button" aria-current={t.id === id} onClick={() => { setId(t.id); setData(null); }}
            style={{ display: "block", width: "100%", textAlign: "left", background: t.id === id ? "#1e293b" : "none", border: 0, color: "inherit", padding: "4px 6px", cursor: "pointer" }}>
            <strong>{t.id}</strong> {t.title}
          </button>
        ))}
        <button type="button" onClick={onClose} style={{ marginTop: 12 }}>Close</button>
      </nav>
      <main style={{ flex: 1, padding: 12, overflow: "auto", position: "relative" }}>
        <h2 style={{ margin: "0 0 8px", font: "600 15px system-ui" }}>{id}{pick ? ` · ${pick.title}` : ""}</h2>
        <canvas ref={canvas} aria-label={`${id} machines`} style={{ position: "static", maxWidth: "100%", cursor: hit ? "pointer" : "default" }}
          onMouseMove={(e) => { const [h, d] = at(e); setHit(h); setTip(d); }} onMouseLeave={() => { setHit(null); setTip(null); }} onClick={(e) => setData(at(e)[1])} />
        {tip && <aside role="tooltip" style={{ position: "absolute", top: 12, right: 12, background: "#111827", border: "1px solid #334155", padding: 8, maxWidth: 260 }}>
          <strong>{tip.title}</strong>{tip.lines.map((l) => <div key={l}>{l}</div>)}{tip.trace.map((l, i) => <div key={i} style={{ opacity: 0.7 }}>{l}</div>)}
        </aside>}
        {data && <section aria-label="Data" style={{ marginTop: 8 }}>
          <strong>{data.title}</strong>{data.lines.map((l) => <div key={l}>{l}</div>)}{data.trace.map((l, i) => <div key={i} style={{ opacity: 0.7 }}>{l}</div>)}
        </section>}
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
          <button type="button" disabled={replay.live} onClick={() => setReplay(replay.playing ? pause(replay) : play(replay))}>{replay.playing ? "Pause" : "Play"}</button>
          <input type="range" aria-label="Replay time" min={0} max={WINDOW} step={60} value={WINDOW - ago} style={{ flex: 1 }}
            onChange={(e) => setReplay(scrubTo(replay, now - WINDOW + Number(e.target.value), now))} />
          <button type="button" aria-pressed={replay.live} onClick={() => setReplay(goLive(replay, now))}>Live</button>
        </div>
      </main>
    </div>
  );
}
