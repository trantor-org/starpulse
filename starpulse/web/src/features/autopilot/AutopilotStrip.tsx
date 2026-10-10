// The Kanban toolbar's autopilot strip: the global switch, each capacity dimension's use against its limit, the sessions in flight and the
// next pick with why it goes or waits. Off stops admission only, so the strip dims and counts the sessions still running.
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { ago } from "../../shared/clock";
import { useViewActive } from "../../shared/Kept";
import { level, type AutopilotStore, type Dimension, type InFlight, type NextPick } from "./autopilot";

/** The sampler emits on a headroom crossing; the strip also re-reads on this interval so its meters move with the host. */
const REFRESH_MS = 5000;

const pct = (d: Dimension) => `${Math.min(100, (d.used / d.limit) * 100)}%`;

function Meter({ d, children }: { d: Dimension; children?: ReactNode }) {
  return (
    <div className={`dm ${level(d)}`} title={d.detail}>
      <div className="r"><span>{d.label}</span><b>{Math.round(d.used)}/{d.limit}{d.unit}</b></div>
      <div className="m"><i style={{ width: pct(d) }} /></div>
      {children}
    </div>
  );
}

/** The menu under the Sessions meter; `sessions` is null while the server does not list them. */
function Sessions({ d, sessions, now, close }: { d: Dimension; sessions: InFlight[] | null; now: number; close: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close]);
  return (
    <div className="menu ap-ses" role="menu" aria-label="Sessions in flight">
      <div className="hd">In flight · {d.used} of {d.limit}</div>
      {sessions === null && <div className="none">The server does not list its sessions yet.</div>}
      {sessions?.length === 0 && <div className="none">No autopilot session is running.</div>}
      {sessions?.map((s) => (
        <a key={s.task} role="menuitem" href={s.url} target="_blank" rel="noreferrer">
          <span className="id">{s.task}</span><span className="tt">{s.title}</span><span className="md">{s.model} · {ago(now - s.started)}</span>
        </a>
      ))}
    </div>
  );
}

const why = (next: NextPick) => (next.verdict === "starting" ? "starting" : `waits: ${next.reason}`);

export function AutopilotStrip({ store, now, openTask }: { store: AutopilotStore; now: number; openTask: (id: string) => void }) {
  const { current, phase, unavailable } = useSyncExternalStore(store.subscribe, store.get);
  const [menu, setMenu] = useState(false);
  const active = useViewActive();
  useEffect(() => {
    if (!active) return;
    void store.load();
    const refresh = setInterval(() => void store.load(), REFRESH_MS);
    return () => clearInterval(refresh);
  }, [store, active]);
  if (!current) return unavailable ? <span className="ap down" title={unavailable}>Autopilot unavailable</span> : null;
  const { on, dimensions, inFlight, next } = current;
  const running = dimensions.find((d) => d.name === "sessions")?.used ?? inFlight?.length ?? 0;
  return (
    <div className={`ap${on ? "" : " off"}`}>
      <label className="sw-l">
        <button type="button" className="sw" role="switch" aria-checked={on} aria-label="Autopilot" disabled={phase.kind === "saving"}
          onClick={() => void store.setOn(!on)} />
        Autopilot
      </label>
      <div className="dims">
        {dimensions.map((d) =>
          d.name === "sessions" ? (
            <div key={d.name} className="fw">
              <button type="button" className="dmb" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((m) => !m)}><Meter d={d} /></button>
              {menu && <Sessions d={d} sessions={inFlight} now={now} close={() => setMenu(false)} />}
            </div>
          ) : <Meter key={d.name} d={d} />,
        )}
      </div>
      {!on && <span className="paused" title={`${running === 1 ? "1 session" : `${running} sessions`} still running`}>Paused · {running} running</span>}
      {on && (next ? (
        // the pick's color carries its state (green starting, yellow waiting); the words stay on hover and for screen readers
        <button type="button" className={`nx ${next.verdict}`} title={`${why(next)} · ${next.title}`} aria-label={`Next ${next.task}, ${why(next)}`}
          onClick={() => openTask(next.task)}>
          Next <b>{next.task}</b>
        </button>
      ) : <span className="nx none">Next · nothing eligible</span>)}
      {phase.kind === "refused" && (
        <div className="refusal ap-ref" role="alert">
          <div className="k">the server refused the change</div><div className="via">{phase.reason}<button type="button" className="dismiss" aria-label="Dismiss" onClick={() => store.dismiss()}>✕</button></div>
        </div>
      )}
    </div>
  );
}
