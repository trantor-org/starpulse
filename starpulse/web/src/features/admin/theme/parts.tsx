// What the Theme card and its two dialogs share: status names, swatch rows, the modal frame, the scheme source, the sample surface and
// the contrast nudges. Swatches carry data-theme-raw: they show a pack's own colors, never the page's.
import type { ReactNode } from "react";
import { DISTINCT, NEUTRALS, fromBase16, type Neutrals, type Nudge } from "./scheme";

export const ROLE_LABEL: Record<string, string> = {
  ok: "passing", run: "running", fail: "failing", agent: "agent", hold: "held", waits: "waits on", ready: "ready", released: "released", phase: "phase",
};
/** A ΔE as the dialogs print it: three decimals and no leading zero. */
export const de = (d: number) => d.toFixed(3).replace(/^0/, "");

export function Swatches({ t }: { t: Record<string, string> }) {
  return <span className="sws" data-theme-raw="">{DISTINCT.map((k) => <i key={k} title={ROLE_LABEL[k]} style={{ background: t[k] }} />)}</span>;
}

export function Ramp({ n }: { n: Neutrals }) {
  return <span className="ramp" data-theme-raw="">{NEUTRALS.map((k) => <i key={k} title={k} style={{ background: n[k] }} />)}</span>;
}

export function Modal({ label, close, children }: { label: string; close: () => void; children: ReactNode }) {
  return (
    <div id="kbm" className="thm" onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="modal ask" role="dialog" aria-modal="true" aria-label={label} onKeyDown={(e) => e.key === "Escape" && close()}>
        <button type="button" className="x" onClick={close} aria-label="Close">✕</button>
        <h2>{label}</h2>
        {children}
      </div>
    </div>
  );
}

/** The scheme's text from a file or the paste box: one source, so a picked file shows in the box it can be edited in. */
export function SchemeSource({ text, setText }: { text: string; setText: (v: string) => void }) {
  return (
    <>
      <div className="row">
        <span className="lb">File</span>
        <input type="file" accept=".yaml,.yml,.txt" aria-label="Scheme file" onChange={(e) => void e.target.files?.[0]?.text().then(setText)} />
      </div>
      <div className="row">
        <span className="lb">Or paste</span>
        <textarea className="yaml" rows={5} spellCheck={false} aria-label="Scheme YAML" placeholder={"scheme: \"One Dark\"\nbase00: \"282c34\"\n…"} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
    </>
  );
}

/** A surface drawn in the theme's own tokens: the words a page sets on it and one chip per status. */
export function Sample({ t }: { t: Record<string, string> }) {
  return (
    <div className="sample" data-theme-raw="" style={{ background: t.surface, borderColor: t.track }}>
      <div style={{ color: t.ink }}>DEMO-12 · Admin theme picker <span style={{ color: t.muted }}>· 2h ago</span></div>
      <div className="chips">
        {DISTINCT.map((k) => (
          <span key={k} style={{ color: t[`${k}-text`], borderColor: t[k] }}><i style={{ background: t[k] }} />{ROLE_LABEL[k]}</span>
        ))}
      </div>
    </div>
  );
}

export function Nudges({ nudged }: { nudged: Nudge[] }) {
  if (!nudged.length) return null;
  return (
    <div className="nudges">
      <div className="k">Lifted to read on the surface</div>
      <ul data-theme-raw="">
        {nudged.map((x) => <li key={x.key}><span className="nk">{x.key}</span><i style={{ background: x.from }} /><code>{x.from}</code>→<i style={{ background: x.to }} /><code>{x.to}</code></li>)}
      </ul>
    </div>
  );
}

/** The scheme in `text`, the Error that says why it is not one, or null for an empty box. */
export function parseScheme(text: string) {
  if (!text.trim()) return null;
  try {
    return fromBase16(text);
  } catch (e) {
    return e instanceof Error ? e : new Error(String(e));
  }
}
