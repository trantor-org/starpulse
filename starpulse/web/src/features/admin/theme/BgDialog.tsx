// Adds a background: the neutral ramp of one picked color, or of base00-07 of a scheme file. A ramp whose surface is not dark
// (`bgRefusal`) is refused and saves nothing.
import { useMemo, useState } from "react";
import { Modal, Nudges, Ramp, Sample, SchemeSource, parseScheme } from "./parts";
import { bgRefusal, build, rampFrom } from "./scheme";
import type { ThemeStore } from "./themeStore";

const HEX = /^#[0-9a-fA-F]{6}$/;

export function BgDialog({ theme, close }: { theme: ThemeStore; close: () => void }) {
  const [from, setFrom] = useState<"color" | "scheme">("color");
  const [pick, setPick] = useState("#2a1f3d");
  const [draft, setDraft] = useState(pick);
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const parsed = useMemo(() => (from === "scheme" ? parseScheme(text) : null), [from, text]);
  const scheme = parsed instanceof Error ? null : parsed;
  const n = useMemo(() => (from === "color" ? rampFrom(pick) : scheme?.bg ?? null), [from, pick, scheme]);
  const refused = n && bgRefusal(n);
  const built = useMemo(() => (n && !refused ? build(theme.packOf(theme.get().pack), n) : null), [n, refused, theme]);
  const fallback = from === "color" ? `Background ${pick}` : scheme?.name ?? "";
  const save = () => {
    if (!n || refused) return;
    theme.addBg(name.trim() || fallback, n);
    close();
  };
  const color = (v: string) => {
    setDraft(v);
    if (HEX.test(v)) setPick(v.toLowerCase());
  };
  return (
    <Modal label="Add a background" close={close}>
      <div className="opt">
        <div className="row">
          <span className="lb">From</span>
          <div className="seg">
            <button type="button" className={from === "color" ? "on" : ""} aria-pressed={from === "color"} onClick={() => setFrom("color")}>One color</button>
            <button type="button" className={from === "scheme" ? "on" : ""} aria-pressed={from === "scheme"} onClick={() => setFrom("scheme")}>A scheme file</button>
          </div>
        </div>
        {from === "color"
          ? <div className="row">
              <span className="lb">Surface</span>
              <span className="pickc">
                <input type="color" value={pick} aria-label="Surface color" onChange={(e) => color(e.target.value)} />
                <input className="hexin" value={draft} aria-label="Surface hex" maxLength={7} onChange={(e) => color(e.target.value)} />
                <span className="hint">panels sit on it; the rest steps from it</span>
              </span>
            </div>
          : <SchemeSource text={text} setText={setText} />}
        {n && <div className="row"><span className="lb">Ramp</span><Ramp n={n} /></div>}
        <div className="row"><span className="lb">Name</span><input className="nmin" value={name} placeholder={fallback} aria-label="Background name" maxLength={40} onChange={(e) => setName(e.target.value)} /></div>
      </div>
      {parsed instanceof Error && <div className="refusal" role="alert"><div className="k">Not read</div>{parsed.message}</div>}
      {refused && <div className="refusal" role="alert"><div className="k">Not added</div>{refused}</div>}
      {built && <>
        <Sample t={built.t} />
        <Nudges nudged={built.nudged} />
      </>}
      <div className="afoot">
        <button type="button" className="cancel" onClick={close}>Cancel</button>
        <button type="button" className="startbtn sp" disabled={!n || !!refused} onClick={save}>Add and apply</button>
      </div>
    </Modal>
  );
}
