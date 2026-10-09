// The Admin view: this browser's settings in a main-area view like the Kanban. Font size, Motion, Opens on, Kanban cards and Clock; the
// Preview card draws a Star Map label and a Kanban card at the chosen scale and density, so the choice is judged before leaving the view.
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { SCALE, labelPx, type AdminStore } from "./adminPrefs";
import { clockHm, type ClockMode } from "../../shared/clock";
import { CHIPS, type HistoryWindowStore } from "./historyWindow";

/** The Preview's Star Map label: a ring with a state's name and count beneath, sized as the renderer sizes them. */
function drawPreview(c: HTMLCanvasElement, scale: number) {
  const r = c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  c.width = r.width * dpr;
  c.height = r.height * dpr;
  const cx = c.getContext("2d");
  if (!cx) return;
  cx.scale(dpr, dpr);
  const x = r.width / 2, y = r.height / 2 - 14, name = labelPx(12.5, 1, scale), sub = labelPx(10.5, 1, scale);
  cx.strokeStyle = "rgba(167,139,250,.8)";
  cx.lineWidth = 1;
  cx.beginPath();
  cx.arc(x, y, 9, 0, 7);
  cx.stroke();
  cx.textAlign = "center";
  cx.textBaseline = "middle";
  cx.letterSpacing = "0.6px";
  cx.font = `300 ${name}px Inter, system-ui, sans-serif`;
  cx.fillStyle = "rgba(207,217,234,.9)";
  cx.fillText("In Progress", x, y + 14 + name / 2 + 4);
  cx.font = `300 ${sub}px Inter, system-ui, sans-serif`;
  cx.fillStyle = "rgba(148,163,184,.6)";
  cx.fillText("4 tasks", x, y + 14 + name * 1.5 + 8);
}

function Preview({ scale, compact }: { scale: number; compact: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const draw = () => drawPreview(c, scale);
    draw();
    // the card's width also changes when the navigator folds, not only with the window
    const watch = new ResizeObserver(draw);
    watch.observe(c);
    return () => watch.disconnect();
  }, [scale]);
  return (
    <section className="card">
      <h2>Preview</h2>
      <div className="pv">
        <div className="pvk">Star Map label</div>
        <canvas ref={canvas} />
        <div className="pvk">Kanban card</div>
        <div className={compact ? "pvcard compact" : "pvcard"}>
          <div className="top"><span className="id">DEMO-101</span><span className="pr"><i />#2094</span></div>
          <div className="t">Sample card: how a title reads at this size</div>
          {!compact && <div className="foot2"><span className="lab">feature</span><span className="lab">size-3</span><span className="lab">needs-human</span></div>}
        </div>
      </div>
    </section>
  );
}

/** A row of exclusive choices, one pressed. */
function Seg<T extends string>({ label, value, options, onPick }: { label: string; value: T; options: readonly (readonly [T, string])[]; onPick: (v: T) => void }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, name]) => <button key={v} type="button" aria-pressed={v === value} onClick={() => onPick(v)}>{name}</button>)}
    </div>
  );
}

/** The time of the example beside the Clock choice, written as the choice writes every time on the page. */
const sample = (clock: "24" | "12") => clockHm(Date.now() / 1000, clock);

/** The Server card: the history window every viewer shares, which the server keeps and validates. */
function ServerCard({ store, clock }: { store: HistoryWindowStore; clock: "24" | "12" }) {
  const { current, draft, phase, unavailable } = useSyncExternalStore(store.subscribe, store.get);
  useEffect(() => void store.load(), [store]);
  const dirty = store.dirty(), saving = phase.kind === "saving";
  return (
    <section className="card">
      <h2>Server <span className="c">shared by every viewer</span></h2>
      <div className="row">
        <div><div className="lb">History window</div><div className="hint">How far back a task's latest move on a machine counts</div></div>
        <div>
          {!current ? (
            unavailable && <div className="refusal"><div className="k">the history window cannot be read</div>{unavailable}</div>
          ) : (
            <>
              <div className="hours">
                <input inputMode="decimal" value={draft} aria-label="History window in hours" onChange={(e) => store.edit(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && dirty) void store.save();
                    if (e.key === "Escape") store.edit(String(current.hours));
                  }} /> hours
                <div className="chips">{CHIPS.map((h) => <button key={h} type="button" onClick={() => store.edit(String(h))}>{h}h</button>)}</div>
                <button type="button" className="btn go" disabled={!dirty || saving} onClick={() => void store.save()}>{saving ? "Saving…" : "Save"}</button>
              </div>
              <div className="hint">Default {current.default} h, declared by --hours. <button type="button" className="link" onClick={() => void store.reset()}>Reset to default</button></div>
              {phase.kind === "saved" && <div className="ok">Saved: every viewer counts the last {current.hours} h from the next snapshot · <span className="when">{clockHm(phase.at, clock)}</span></div>}
              {phase.kind === "refused" && <div className="refusal"><div className="k">the server refused the change</div>{phase.reason}</div>}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

/** `forwarding` draws the Forwarding card in the settings column: the card is its own feature, so App hands it in with the clock it is to show. */
export function Admin({ store, window: historyWindow, forwarding }: { store: AdminStore; window: HistoryWindowStore; forwarding: (clock: ClockMode) => ReactNode }) {
  const { scale, motion, view, density, clock } = useSyncExternalStore(store.subscribe, store.get);
  return (
    <div id="admin">
      <header><span className="title">Admin</span><span className="count">settings for this browser and for the StarPulse server</span></header>
      <div className="grid">
        <div>
          <section className="card">
            <h2>This browser <span className="c">kept on this device only</span></h2>
            <div className="row">
              <div><div className="lb">Font size</div><div className="hint">Panels, Kanban cards and Star Map labels</div></div>
              <div>
                <div className="scale">
                  <input type="range" min={SCALE.min} max={SCALE.max} step={SCALE.step} value={scale} aria-label="Font size" aria-valuetext={`${scale}%`}
                    onChange={(e) => store.setScale(Number(e.target.value))} />
                  <span className="pct">{scale}%</span>
                </div>
                <div className="ticks">
                  {SCALE.ticks.map((v) => <button key={v} type="button" onClick={() => store.setScale(v)}>{v}%</button>)}
                </div>
              </div>
            </div>
            <div className="row">
              <div><div className="lb">Motion</div><div className="hint">Pulses travel, cards animate and the Star Map redraws as it moves</div></div>
              <div><button type="button" className="sw" role="switch" aria-checked={motion} aria-label="Motion" onClick={() => store.setMotion(!motion)} /></div>
            </div>
            <div className="row">
              <div><div className="lb">Opens on</div><div className="hint">When the address names no view</div></div>
              <Seg label="Opens on" value={view} options={[["constellation", "Star Map"], ["kanban", "Kanban"]]} onPick={(v) => store.setView(v)} />
            </div>
            <div className="row">
              <div><div className="lb">Kanban cards</div><div className="hint">Compact shows one title line, no labels</div></div>
              <Seg label="Kanban cards" value={density} options={[["comfortable", "Comfortable"], ["compact", "Compact"]]} onPick={(v) => store.setDensity(v)} />
            </div>
            <div className="row">
              <div><div className="lb">Clock</div><div className="hint">Navigator time, Recent feed, panels and tooltips, now {sample(clock)} MST</div></div>
              <Seg label="Clock" value={clock} options={[["24", "24-hour"], ["12", "12-hour"]]} onPick={(v) => store.setClock(v)} />
            </div>
            <div className="foot">Changes apply as you make them.<button type="button" className="btn" onClick={() => store.reset()}>Reset this browser</button></div>
          </section>
          <ServerCard store={historyWindow} clock={clock} />
          {forwarding(clock)}
        </div>
        <Preview scale={scale} compact={density === "compact"} />
      </div>
    </div>
  );
}
