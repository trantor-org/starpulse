// The Admin view's Forwarding card: what this instance's forwarder sends the hub, field by field, the rows it would send next, and the opt-in
// that lets a person's name go with them. The body is pure over the store's view so every state draws without a server.
import { useEffect, useSyncExternalStore } from "react";
import { clockHm, type ClockMode } from "./clock";
import type { ForwardStatus, ForwardingStore, ForwardingView } from "./forwarding";

/** How often the card re-reads what is queued; the forwarder moves on its own interval, so the listing drifts while the view is open. */
const REFRESH_MS = 5000;

const show = (key: string, value: string | number | string[], clock: ClockMode) =>
  key === "time" && typeof value === "number" ? clockHm(value, clock) : Array.isArray(value) ? value.join(", ") : String(value);

function Contract({ status }: { status: ForwardStatus }) {
  const kept = [...new Set(status.next.flatMap((row) => row.kept))].sort();
  return (
    <>
      <table className="fw-contract">
        <tbody>
          {Object.entries(status.contract).flatMap(([stream, fields]) => [
            <tr key={stream} className="stream"><th colSpan={2}>{stream}</th></tr>,
            ...fields.map(({ field, person }) => (
              <tr key={`${stream}/${field}`}><td>{field}</td><td className={person ? "after" : "sent"}>{person ? "after opt-in" : "sent"}</td></tr>
            )),
          ])}
        </tbody>
      </table>
      <div className="hint">
        Never sent: session, tool and prompt detail, or any field a stream's contract does not list.
        {kept.length > 0 && <> Kept here in the rows below: {kept.join(", ")}.</>}
      </div>
    </>
  );
}

function Queue({ status, clock }: { status: ForwardStatus; clock: ClockMode }) {
  if (!status.next.length) return <div className="hint">Nothing waiting to send.</div>;
  return (
    <ul className="fw-next">
      {status.next.map((row, i) => (
        <li key={i}>
          <span className="stream">{row.stream}</span>
          {Object.entries(row.fields).map(([key, value]) => <span key={key} className="kv"><b>{key}</b> {show(key, value, clock)}</span>)}
        </li>
      ))}
      {status.more && <li className="more">+ more waiting</li>}
    </ul>
  );
}

export function ForwardingBody({ view, clock, onToggle }: { view: ForwardingView; clock: ClockMode; onToggle: (on: boolean) => void }) {
  const { current, phase, unavailable } = view;
  if (!current)
    return unavailable ? <div className="row"><div className="refusal"><div className="k">the forwarding status cannot be read</div>{unavailable}</div></div> : null;
  if (!current.configured) return <div className="row"><div className="hint">This instance forwards nothing: its config has no [forward] block.</div></div>;
  const saving = phase.kind === "saving";
  return (
    <>
      <div className="row">
        <div>
          <div className="lb">Hub</div>
          <div className="hint">{current.lastSent == null ? "Nothing sent since this process started" : <>Last sent <span className="when">{clockHm(current.lastSent, clock)}</span></>}</div>
        </div>
        <div className="fw-url">{current.url}</div>
      </div>
      <div className="row">
        <div><div className="lb">Send names</div><div className="hint">{current.names ? "Names go with each batch" : "Names stay on this instance"}</div></div>
        <div>
          <button type="button" className="sw" role="switch" aria-checked={current.optIn} aria-label="Send names to the hub" disabled={saving} onClick={() => onToggle(!current.optIn)} />
          {phase.kind === "saved" && <div className="ok">Saved: the next batch {current.names ? "carries" : "withholds"} names · <span className="when">{clockHm(phase.at, clock)}</span></div>}
          {phase.kind === "refused" && <div className="refusal"><div className="k">the server refused the change</div>{phase.reason}</div>}
        </div>
      </div>
      {(current.refused || current.problem) && (
        <div className="row"><div className="refusal">
          <div className="k">{current.refused ? "the hub refused names" : "the hub did not take the last batch"}</div>
          {current.problem}
          {current.refused && " Names stay on this instance until the hub accepts them."}
        </div></div>
      )}
      <div className="row fw-block"><div><div className="lb">What is sent</div></div><Contract status={current} /></div>
      <div className="row fw-block"><div><div className="lb">Next batch</div><div className="hint">As the hub would receive it</div></div><Queue status={current} clock={clock} /></div>
    </>
  );
}

export function ForwardingCard({ store, clock }: { store: ForwardingStore; clock: ClockMode }) {
  const view = useSyncExternalStore(store.subscribe, store.get);
  useEffect(() => {
    void store.load();
    const refresh = setInterval(() => void store.load(), REFRESH_MS);
    return () => clearInterval(refresh);
  }, [store]);
  return (
    <section className="card">
      <h2>Forwarding <span className="c">what this instance sends the hub</span></h2>
      <ForwardingBody view={view} clock={clock} onToggle={(on) => void store.setOptIn(on)} />
    </section>
  );
}
