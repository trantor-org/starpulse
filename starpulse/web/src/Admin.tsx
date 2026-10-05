// The Admin view: this browser's settings in a main-area view like the Kanban. Font size is the first; the Preview card draws a Star Map
// label and a Kanban card at the chosen scale, so the choice is judged before leaving the view.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { SCALE, labelPx, type AdminStore } from "./adminPrefs";

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

function Preview({ scale }: { scale: number }) {
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
        <div className="pvcard">
          <div className="top"><span className="id">DEMO-101</span><span className="pr"><i />#2094</span></div>
          <div className="t">Sample card: how a title reads at this size</div>
          <div className="foot2"><span className="lab">feature</span><span className="lab">size-3</span><span className="lab">needs-human</span></div>
        </div>
      </div>
    </section>
  );
}

export function Admin({ store }: { store: AdminStore }) {
  const { scale } = useSyncExternalStore(store.subscribe, store.get);
  return (
    <div id="admin">
      <header><span className="title">Admin</span><span className="count">settings for this browser</span></header>
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
            <div className="foot">Changes apply as you make them.<button type="button" className="btn" onClick={() => store.reset()}>Reset this browser</button></div>
          </section>
        </div>
        <Preview scale={scale} />
      </div>
    </div>
  );
}
