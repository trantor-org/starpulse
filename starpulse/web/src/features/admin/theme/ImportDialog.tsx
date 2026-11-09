// Imports a base16 or base24 scheme as a color pack, and as a background unless that is refused. The dE gate runs on the built tokens:
// a closest pair under REFUSE_DE saves nothing, one under WARN_DE saves with a warning that names the two roles.
import { useMemo, useState } from "react";
import { Modal, Nudges, Ramp, ROLE_LABEL, Sample, SchemeSource, de, parseScheme } from "./parts";
import { REFUSE_DE, WARN_DE, bgRefusal, build, closest } from "./scheme";
import type { ThemeStore } from "./themeStore";

export function ImportDialog({ theme, close }: { theme: ThemeStore; close: () => void }) {
  const [text, setText] = useState("");
  const [name, setName] = useState<string | null>(null);
  const [withBg, setWithBg] = useState(true);
  const parsed = useMemo(() => parseScheme(text), [text]);
  const scheme = parsed instanceof Error ? null : parsed;
  const bgNo = scheme && bgRefusal(scheme.bg);
  const useBg = !!scheme && withBg && !bgNo;
  const built = useMemo(() => scheme && build(scheme.pack, useBg ? scheme.bg : theme.bgOf(theme.get().bg)), [scheme, useBg, theme]);
  const [d, a, b] = built ? closest(built.t) : [Infinity, "", ""];
  const refused = d < REFUSE_DE;
  const save = () => {
    if (!scheme || refused) return;
    theme.addPack({ ...scheme.pack, name: (name ?? scheme.name).trim() || scheme.name }, useBg ? scheme.bg : undefined);
    close();
  };
  return (
    <Modal label="Import a color scheme" close={close}>
      <div className="opt">
        <SchemeSource text={text} setText={(v) => { setText(v); setName(null); }} />
        {scheme && <>
          <div className="row"><span className="lb">Name</span><input className="nmin" value={name ?? scheme.name} aria-label="Pack name" maxLength={40} onChange={(e) => setName(e.target.value)} /></div>
          <div className="row">
            <span className="lb">Background</span>
            <label className={`withbg${bgNo ? " off" : ""}`}><input type="checkbox" checked={useBg} disabled={!!bgNo} onChange={(e) => setWithBg(e.target.checked)} /> Also add its background<Ramp n={scheme.bg} /></label>
          </div>
          {bgNo && <div className="note wide">{bgNo} The pack imports on your current background.</div>}
        </>}
      </div>
      {parsed instanceof Error && <div className="refusal" role="alert"><div className="k">Not read</div>{parsed.message}</div>}
      {built && <>
        <Sample t={built.t} />
        {refused
          ? <div className="refusal" role="alert"><div className="k">Not imported</div>{ROLE_LABEL[a]} and {ROLE_LABEL[b]} are too alike to tell apart on the Star Map (ΔE {de(d)}; needs {de(REFUSE_DE)}).</div>
          : d < WARN_DE
            ? <div className="warn" role="status"><b>Close pair:</b> {ROLE_LABEL[a]} and {ROLE_LABEL[b]} are near (ΔE {de(d)}). It imports; check them on the map.</div>
            : <div className="okline" role="status">Every status stands apart: the closest pair, {ROLE_LABEL[a]} and {ROLE_LABEL[b]}, is ΔE {de(d)}.</div>}
        <Nudges nudged={built.nudged} />
      </>}
      <div className="afoot">
        <button type="button" className="cancel" onClick={close}>Cancel</button>
        <button type="button" className="startbtn sp" disabled={!scheme || refused} onClick={save}>Import and apply</button>
      </div>
    </Modal>
  );
}
