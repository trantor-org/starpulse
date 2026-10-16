// The Admin view's Autopilot card: the global switch, the harness Segments, each capacity dimension's use against its
// limit, the next pick as text with why it goes or waits, the count of sessions in flight and the quiet hours. Status
// arrives on /api/events; one GET syncs on view open. Off stops admission; the card dims and counts the sessions still
// running from its last reading.
import { useEffect, useSyncExternalStore } from "react";
import { clockHm } from "../../shared/clock";
import { useViewActive } from "../../shared/Kept";
import type { QuietHoursStore } from "../admin/quietHours";
import {
  level,
  type AutopilotState,
  type AutopilotStore,
  type Dimension,
  type HarnessOption,
  type NextPick,
  type Pause,
} from "./autopilot";

const pct = (d: Dimension) => `${Math.min(100, (d.used / d.limit) * 100)}%`;

function Meter({ d }: { d: Dimension }) {
  return (
    <div className={`dm ${level(d)}`} title={d.detail}>
      <div className="r"><span>{d.label}</span><b>{Math.round(d.used)}/{d.limit}{d.unit}</b></div>
      <div className="m"><i style={{ width: pct(d) }} /></div>
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

/** Tooltip / hint for a credit pause: `credits until 14:00` in the Admin clock. */
const creditHint = (pause: Pause | undefined, clock: "24" | "12") =>
  pause ? `credits until ${clockHm(pause.until, clock)}` : "";

function optionReason(h: HarnessOption, pauses: Pause[], clock: "24" | "12"): string | undefined {
  const paused = pauses.find((p) => p.harness === h.name);
  if (paused) return creditHint(paused, clock);
  if (!h.sessions) return h.reason || "runs no sessions";
  return undefined;
}

function labelOf(name: string, options: HarnessOption[]) {
  return options.find((h) => h.name === name)?.label ?? name;
}

function capacityHint(current: AutopilotState, options: HarnessOption[]) {
  const selected = labelOf(current.harness, options);
  const other = Object.keys(current.sessionsByHarness).find((n) => n !== current.harness)
    ?? options.find((h) => h.name !== current.harness)?.name;
  if (!other) return `${selected}'s session cap`;
  const row = current.sessionsByHarness[other] ?? { use: 0, limit: 0 };
  return `${selected}'s session cap; ${labelOf(other, options)} ${Math.round(row.use)}/${row.limit} running`;
}

export function AutopilotCard({ store, quiet, clock }: { store: AutopilotStore; quiet: QuietHoursStore; clock: "24" | "12" }) {
  const { current, phase, unavailable, harnesses } = useSyncExternalStore(store.subscribe, store.get);
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
  const { on, dimensions, inFlight, next, harness, pauses } = current;
  const running = dimensions.find((d) => d.name === "sessions")?.used ?? inFlight?.length ?? 0;
  const selectedPause = pauses.find((p) => p.harness === harness);
  const selectedLabel = labelOf(harness, harnesses);
  return (
    <section className={`card ap${on ? "" : " off"}`}>
      {head}
      <div className="row">
        <div>
          <div className="lb">Admission</div>
          <div className="hint">Off starts nothing; sessions already running continue. Starts on the picked harness.</div>
        </div>
        <div>
          <div className="hours">
            <button type="button" className="sw" role="switch" aria-checked={on} aria-label="Autopilot" disabled={phase.kind === "saving"}
              onClick={() => void store.setOn(!on)} />
            <span className="state">{on ? "On" : "Paused"}</span>
            {harnesses.length > 1 && (
              <span className="seg" role="radiogroup" aria-label="Harness">
                {harnesses.map((h) => {
                  const reason = optionReason(h, pauses, clock);
                  return (
                    <button key={h.name} type="button" role="radio" aria-pressed={h.name === harness}
                      disabled={!!reason || phase.kind === "saving"} title={reason}
                      onClick={() => void store.setHarness(h.name)}>{h.label}</button>
                  );
                })}
              </span>
            )}
          </div>
          {selectedPause && <div className="hint">{creditHint(selectedPause, clock)}</div>}
          {phase.kind === "refused" && (
            <div className="refusal" role="alert">
              <div className="k">the server refused the change</div><div className="via">{phase.reason}<button type="button" className="dismiss" aria-label="Dismiss" onClick={() => store.dismiss()}>✕</button></div>
            </div>
          )}
        </div>
      </div>
      <div className="row">
        <div><div className="lb">Capacity</div><div className="hint">{capacityHint(current, harnesses)}</div></div>
        <div className="dims">{dimensions.map((d) => <Meter key={d.name} d={d} />)}</div>
      </div>
      <div className="row">
        <div><div className="lb">Next pick</div><div className="hint">The Ready task autopilot starts next, or what it waits on</div></div>
        <Next on={on} next={next} />
      </div>
      <div className="row">
        <div><div className="lb">In flight</div><div className="hint">Autopilot's sessions running now on {selectedLabel}</div></div>
        <div className="inflight">{running} running</div>
      </div>
      <QuietRow store={quiet} clock={clock} />
    </section>
  );
}
