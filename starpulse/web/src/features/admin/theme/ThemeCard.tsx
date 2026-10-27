// The Admin's Theme card: a color pack and a background for this browser, each a tile that applies on click, with the built-in
// packs, the ones imported here, and the dialogs that import a base16 or base24 scheme or make a background from one color.
import { useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { BgDialog } from "./BgDialog";
import { ImportDialog } from "./ImportDialog";
import { Ramp, Swatches } from "./parts";
import { BUILTIN, SLATE, build, type Neutrals, type Pack } from "./scheme";
import type { ThemeStore } from "./themeStore";

/** A tile's name as a field: Enter or a blur keeps what was typed, Escape keeps the old name, and only the first of them counts. */
function RenameField({ name, done }: { name: string; done: (v: string | null) => void }) {
  const [draft, setDraft] = useState(name);
  const settled = useRef(false);
  const finish = (v: string | null) => {
    if (settled.current) return;
    settled.current = true;
    done(v);
  };
  return (
    <input className="ren" autoFocus value={draft} aria-label={`Rename ${name}`} maxLength={40} onChange={(e) => setDraft(e.target.value)}
      onBlur={() => finish(draft)} onKeyDown={(e) => {
        if (e.key === "Enter") finish(draft);
        if (e.key === "Escape") finish(null);
      }} />
  );
}

/** A tile for a pack or background this browser imported, with its Rename field and its in-page Delete confirmation. */
function Own({ name, rename, remove, children }: { name: string; rename: (v: string) => void; remove: () => void; children: (title: ReactNode) => ReactNode }) {
  const [mode, setMode] = useState<"rename" | "delete" | null>(null);
  const renamed = (v: string | null) => {
    if (v?.trim()) rename(v.trim());
    setMode(null);
  };
  return (
    <div className="own">
      {children(mode === "rename" ? <RenameField name={name} done={renamed} /> : null)}
      {mode === "delete"
        ? <div className="acts conf" role="group" aria-label={`Delete ${name}?`}>Delete {name}? <button type="button" className="link del" autoFocus onClick={remove}>Delete</button><button type="button" className="link" onClick={() => setMode(null)}>Keep</button></div>
        : mode === null && <div className="acts"><button type="button" className="link" onClick={() => setMode("rename")}>Rename</button><button type="button" className="link" onClick={() => setMode("delete")}>Delete</button></div>}
    </div>
  );
}

/** A pack's name, vibe and source over its status colors as they read on the chosen background. */
function PackTile({ pack, on, n, choose, title }: { pack: Pack; on: boolean; n: Neutrals; choose: () => void; title?: ReactNode }) {
  const t = useMemo(() => build(pack, n).t, [pack, n]);
  return (
    <div className={`tile${on ? " on" : ""}`}>
      {title && <div className="nm">{title}</div>}
      <button type="button" className="pick" aria-pressed={on} onClick={choose}>
        {!title && <span className="nm">{pack.name}</span>}
        {pack.vibe && <span className="vibe">{pack.vibe}</span>}
        <Swatches t={t} />
        <span className="src">{pack.src?.label ?? ""}</span>
      </button>
    </div>
  );
}

function BgTile({ name, n, on, choose, title }: { name: string; n: Neutrals; on: boolean; choose: () => void; title?: ReactNode }) {
  return (
    <div className={`tile${on ? " on" : ""}`}>
      {title && <div className="nm">{title}</div>}
      <button type="button" className="pick" aria-pressed={on} onClick={choose}>
        {!title && <span className="nm">{name}</span>}
        <Ramp n={n} />
      </button>
    </div>
  );
}

export function ThemeCard({ theme }: { theme: ThemeStore }) {
  const prefs = useSyncExternalStore(theme.subscribe, theme.get);
  const [dialog, setDialog] = useState<"pack" | "bg" | null>(null);
  const n = theme.bgOf(prefs.bg);
  return (
    <section className="card thm">
      <h2>Theme <span className="c">kept on this device only</span></h2>
      <div className="row wide">
        <div><div className="lb">Color pack</div><div className="hint">The status colors: passing, running, failing and the rest. Each swatch row is drawn on your background.</div></div>
        <div className="tiles packs">
          {Object.entries(BUILTIN).map(([id, p]) => <PackTile key={id} pack={p} n={n} on={prefs.pack === id} choose={() => theme.choosePack(id)} />)}
          {prefs.packs.map(({ id, pack }) => (
            <Own key={id} name={pack.name} rename={(v) => theme.renamePack(id, v)} remove={() => theme.deletePack(id)}>
              {(title) => <PackTile pack={pack} n={n} on={prefs.pack === id} choose={() => theme.choosePack(id)} title={title} />}
            </Own>
          ))}
          <button type="button" className="tile add" onClick={() => setDialog("pack")}><span className="plus">+</span>Import scheme<span className="src">base16 or base24 YAML</span></button>
        </div>
      </div>
      <div className="row wide">
        <div><div className="lb">Background</div><div className="hint">The page, panels and text, darkest to lightest. Any pack goes on any background.</div></div>
        <div className="tiles bgs">
          <BgTile name="Slate" n={SLATE} on={prefs.bg === "slate"} choose={() => theme.chooseBg("slate")} />
          {prefs.bgs.map((b) => (
            <Own key={b.id} name={b.name} rename={(v) => theme.renameBg(b.id, v)} remove={() => theme.deleteBg(b.id)}>
              {(title) => <BgTile name={b.name} n={b.n} on={prefs.bg === b.id} choose={() => theme.chooseBg(b.id)} title={title} />}
            </Own>
          ))}
          <button type="button" className="tile add" onClick={() => setDialog("bg")}><span className="plus">+</span>Add background<span className="src">from one color or a scheme</span></button>
        </div>
      </div>
      {dialog === "pack" && <ImportDialog theme={theme} close={() => setDialog(null)} />}
      {dialog === "bg" && <BgDialog theme={theme} close={() => setDialog(null)} />}
    </section>
  );
}
