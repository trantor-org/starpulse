// The Admin view's Autopilot card: the global switch, each capacity dimension's use against its limit, the next pick as text with why it
// goes or waits, the sessions in flight and the quiet hours. Status arrives on /api/events; one GET syncs on view open. Off stops
// admission; the card dims and counts the sessions still running from its last reading.
import { useEffect, useSyncExternalStore } from "react";
import { ago, clockHm } from "../../shared/clock";
import { useViewActive } from "../../shared/Kept";
import type { QuietHoursStore } from "../admin/quietHours";
import { level, type AutopilotStore, type Dimension, type InFlight, type NextPick } from "./autopilot";

const pct = (d: Dimension) => `${Math.min(100, (d.used / d.limit) * 100)}%`;

function Meter({ d }: { d: Dimension }) {
  return (
    <div className={`dm ${level(d)}`} title={d.detail}>
      <div className="r"><span>{d.label}</span><b>{Math.round(d.used)}/{d.limit}{d.unit}</b></div>
      <div className="m"><i style={{ width: pct(d) }} /></div>
    </div>
  );
}

/** The sessions in flight, each linking to its session; `sessions` is null while the server does not list them. */
function Sessions({ sessions, now }: { sessions: InFlight[] | null; now: number }) {
  return (
    <div className="ap-ses">
      {sessions === null && <div className="none">The server does not list its sessions yet.</div>}
      {sessions?.length === 0 && <div className="none">No autopilot session is running.</div>}
      {sessions?.map((s) => (
        <a key={s.task} href={s.url} target="_blank" rel="noreferrer">
          <span className="id">{s.task}</span><span className="tt">{s.title}</span><span className="md">{s.model} · {ago(now - s.started)}</span>
        </a>
      ))}
    </div>
  );
}

const why = (next: NextPick) => (next.verdict === "starting" ? "starting" : `waits: ${next.reason}`);

/** The next pick as text: green when it starts, yellow with what it waits on. */
function Next({ on, next }: { on: boolean; next: NextPick | null }) {
  if (!on) return <div className="nx none">Paused: nothing starts</div>;
  if (!next) return <div className="nx none">Nothing eligible</div>;
  return <div className={`nx ${next.verdict}`}><b className="id">{next.task}</b><span className="tt">{next.title}</span><span className="why">{why(next)}</span></div>;
}

/** The quiet hours row: the daily window in which autopilot starts no task, kept by the server with the switch. */
function QuietRow({ store, clock }: { store: QuietHoursStore; clock: "24" | "12" }) {
  const { loaded, current, draft, phase, unavailable } = useSyncExternalStore(store.subscribe, store.get);
  useEffect(() => void store.load(), [store]);
  const dirty = store.dirty(), saving = phase.kind === "saving";
  return (
    <div className="row">
      <div><div className="lb">Quiet hours</div><div className="hint">Autopilot starts no task in this window; sessions already running continue</div></div>
      <div>
        {!loaded ? (
          unavailable && <div className="refusal"><div className="k">the quiet hours cannot be read</div>{unavailable}</div>
        ) : (
          <>
            <div className="hours">
              <button type="button" className="sw" role="switch" aria-checked={draft.on} aria-label="Autopilot quiet hours" onClick={() => store.edit({ on: !draft.on })} />
              <input type="time" value={draft.start} disabled={!draft.on} aria-label="Quiet hours start" onChange={(e) => store.edit({ start: e.target.value })} />
              to
              <input type="time" value={draft.end} disabled={!draft.on} aria-label="Quiet hours end" onChange={(e) => store.edit({ end: e.target.value })} />
              <button type="button" className="btn go" disabled={!dirty || saving} onClick={() => void store.save()}>{saving ? "Saving…" : "Save"}</button>
            </div>
            <div className="hint">Times in {store.zone()}; an end before the start runs past midnight.</div>
            {phase.kind === "saved" && (
              <div className="ok">
                {current ? `Saved: autopilot starts nothing from ${current.start} to ${current.end}` : "Saved: no quiet hours"} · <span className="when">{clockHm(phase.at, clock)}</span>
              </div>
            )}
            {phase.kind === "refused" && <div className="refusal"><div className="k">the server refused the change</div>{phase.reason}</div>}
          </>
        )}
      </div>
    </div>
  );
}

export function AutopilotCard({ store, quiet, clock, now = Date.now() / 1000 }: { store: AutopilotStore; quiet: QuietHoursStore; clock: "24" | "12"; now?: number }) {
  const { current, phase, unavailable } = useSyncExternalStore(store.subscribe, store.get);
  const active = useViewActive();
  useEffect(() => {
    if (!active) return;
    void store.load();
  }, [store, active]);
  const head = <h2>Autopilot <span className="c">starts Ready tasks on this server</span></h2>;
  if (!current) {
    return (
      <section className="card ap">
        {head}
        {unavailable && <div className="row"><div className="refusal"><div className="k">autopilot cannot be read</div>{unavailable}</div></div>}
      </section>
    );
  }
  const { on, dimensions, inFlight, next } = current;
  const running = dimensions.find((d) => d.name === "sessions")?.used ?? inFlight?.length ?? 0;
  return (
    <section className={`card ap${on ? "" : " off"}`}>
      {head}
      <div className="row">
        <div><div className="lb">Admission</div><div className="hint">Off starts nothing; sessions already running continue</div></div>
        <div>
          <div className="hours">
            <button type="button" className="sw" role="switch" aria-checked={on} aria-label="Autopilot" disabled={phase.kind === "saving"}
              onClick={() => void store.setOn(!on)} />
            <span className="state">{on ? `On · ${running} running` : `Paused · ${running} running`}</span>
          </div>
          {phase.kind === "refused" && (
            <div className="refusal" role="alert">
              <div className="k">the server refused the change</div><div className="via">{phase.reason}<button type="button" className="dismiss" aria-label="Dismiss" onClick={() => store.dismiss()}>✕</button></div>
            </div>
          )}
        </div>
      </div>
      <div className="row">
        <div><div className="lb">Capacity</div><div className="hint">Use against the limit autopilot admits under</div></div>
        <div className="dims">{dimensions.map((d) => <Meter key={d.name} d={d} />)}</div>
      </div>
      <div className="row">
        <div><div className="lb">Next pick</div><div className="hint">The Ready task autopilot starts next, or what it waits on</div></div>
        <Next on={on} next={next} />
      </div>
      <div className="row">
        <div><div className="lb">In flight</div><div className="hint">Autopilot's sessions running now</div></div>
        <Sessions sessions={inFlight} now={now} />
      </div>
      <QuietRow store={quiet} clock={clock} />
    </section>
  );
}
