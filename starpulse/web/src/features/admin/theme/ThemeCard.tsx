// The Admin's Theme card: a color pack and a background for this browser, each a tile that applies on click. Swatches carry
// data-theme-raw: they show a pack's own colors, never the page's.
import { useMemo, useSyncExternalStore } from "react";
import { BUILTIN, DISTINCT, NEUTRALS, SLATE, build, type Neutrals, type Pack } from "./scheme";
import type { ThemeStore } from "./themeStore";

const ROLE_LABEL: Record<string, string> = {
  ok: "passing", run: "running", fail: "failing", agent: "agent", hold: "held", waits: "waits on", ready: "ready", released: "released", phase: "phase",
};

function Swatches({ t }: { t: Record<string, string> }) {
  return <span className="sws" data-theme-raw="">{DISTINCT.map((k) => <i key={k} title={ROLE_LABEL[k]} style={{ background: t[k] }} />)}</span>;
}

function Ramp({ n }: { n: Neutrals }) {
  return <span className="ramp" data-theme-raw="">{NEUTRALS.map((k) => <i key={k} title={k} style={{ background: n[k] }} />)}</span>;
}

/** A pack's name, vibe and source over its status colors as they read on the chosen background. */
function PackTile({ pack, on, n, choose }: { pack: Pack; on: boolean; n: Neutrals; choose: () => void }) {
  const t = useMemo(() => build(pack, n).t, [pack, n]);
  return (
    <div className={`tile${on ? " on" : ""}`}>
      <button type="button" className="pick" aria-pressed={on} onClick={choose}>
        <span className="nm">{pack.name}</span>
        <span className="vibe">{pack.vibe ?? ""}</span>
        <Swatches t={t} />
        <span className="src">{pack.src?.label ?? ""}</span>
      </button>
    </div>
  );
}

function BgTile({ name, n, on, choose }: { name: string; n: Neutrals; on: boolean; choose: () => void }) {
  return (
    <div className={`tile${on ? " on" : ""}`}>
      <button type="button" className="pick" aria-pressed={on} onClick={choose}>
        <span className="nm">{name}</span>
        <Ramp n={n} />
      </button>
    </div>
  );
}

export function ThemeCard({ theme }: { theme: ThemeStore }) {
  const prefs = useSyncExternalStore(theme.subscribe, theme.get);
  const n = theme.bgOf(prefs.bg);
  return (
    <section className="card thm">
      <h2>Theme <span className="c">kept on this device only</span></h2>
      <div className="row wide">
        <div><div className="lb">Color pack</div><div className="hint">The status colors: passing, running, failing and the rest. Each swatch row is drawn on your background.</div></div>
        <div className="tiles packs">
          {Object.entries(BUILTIN).map(([id, p]) => <PackTile key={id} pack={p} n={n} on={prefs.pack === id} choose={() => theme.choosePack(id)} />)}
          {prefs.packs.map(({ id, pack }) => <PackTile key={id} pack={pack} n={n} on={prefs.pack === id} choose={() => theme.choosePack(id)} />)}
        </div>
      </div>
      <div className="row wide">
        <div><div className="lb">Background</div><div className="hint">The page, panels and text, darkest to lightest. Any pack goes on any background.</div></div>
        <div className="tiles bgs">
          <BgTile name="Slate" n={SLATE} on={prefs.bg === "slate"} choose={() => theme.chooseBg("slate")} />
          {prefs.bgs.map((b) => <BgTile key={b.id} name={b.name} n={b.n} on={prefs.bg === b.id} choose={() => theme.chooseBg(b.id)} />)}
        </div>
      </div>
    </section>
  );
}
