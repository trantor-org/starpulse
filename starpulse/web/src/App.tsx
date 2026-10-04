// The page's DOM around the canvas: the left navigator, always shown and foldable to an icon strip,
// the right rail (actors, recent moves, legend), the clock, and the
// tooltip and panel the renderer fills. The canvas is the renderer's; this reads
// what it publishes and asks it to move.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { HudStore, useHud, type HudState } from "./hud";
import { BOARD, pathKey, pathTo, type Path } from "./levels";
import { Kanban } from "./Kanban";
import { MoveStore, postMove } from "./move";
import { FOLD_MS, FoldStore, viewOf, viewSearch, type ViewName } from "./nav";
import { renderer as makeRenderer, type Renderer } from "./renderer";
import { embedded } from "./stream";

/** The actors the rail can hide, in the order it lists them. */

export function App() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const tip = useRef<HTMLDivElement>(null), panel = useRef<HTMLDivElement>(null), clock = useRef<HTMLDivElement>(null);
  const renderer = useRef<Renderer | null>(null);
  const [store] = useState(() => new HudStore());
  const hud = useHud(store);
  const [fold] = useState(() => new FoldStore());
  // a move outlives the view that made it: the card stays where it landed while the writer answers
  const [moves] = useState(() => new MoveStore(postMove));
  const folded = useSyncExternalStore(fold.subscribe, fold.get);
  const [view, setView] = useState<ViewName>(() => viewOf(location.search));
  // the view lives in the address, so a reload or a shared link opens the same one
  const choose = (v: ViewName) => {
    history.replaceState(null, "", `${location.pathname}${viewSearch(location.search, v)}`);
    setView(v);
  };
  useEffect(() => {
    document.body.classList.toggle("kanban", view === "kanban");
    // the canvas was sized while hidden or behind the Kanban; refit it once it is the page again
    if (view === "constellation") renderer.current?.resize();
  }, [view]);

  useEffect(() => {
    const els = { tip: tip.current!, panel: panel.current!, clock: clock.current! };
    const r = makeRenderer(canvas.current!, store, els, new URLSearchParams(location.search).has("demo") || embedded() !== null);
    renderer.current = r;
    r.start();
    return () => r.stop();
  }, [store]);

  // `[` folds the navigator from any view; the canvas takes the width the fold frees
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => fold.onKey(e);
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [fold]);
  // the panel's width animates, so the canvas refits on every frame of it rather than once at the end
  const settled = useRef(true);
  useEffect(() => {
    if (settled.current) {
      settled.current = false;
      return;
    }
    let raf = 0;
    const end = performance.now() + FOLD_MS + 40;
    const tick = () => {
      renderer.current?.resize();
      if (performance.now() < end) raf = requestAnimationFrame(tick);
    };
    // the transition's clock starts a frame after the click, so the last refit waits for its end rather than for the timer
    const done = (e: TransitionEvent) => {
      if (e.target === e.currentTarget && e.propertyName === "width") renderer.current?.resize();
    };
    const nav = document.getElementById("nav");
    nav?.addEventListener("transitionend", done);
    tick();
    return () => {
      cancelAnimationFrame(raf);
      nav?.removeEventListener("transitionend", done);
    };
  }, [folded]);

  return (
    <>
      <canvas ref={canvas} id="c" />
      <Navigator hud={hud} folded={folded} view={view} choose={choose} toggle={() => fold.toggle()} open={(p) => {
          choose("constellation");
          if (pathKey(p) === pathKey(hud.path)) renderer.current?.fitView();
          else renderer.current?.go(p);
        }}
        fly={(g) => renderer.current?.flyToGroup(g)} openDag={(d) => renderer.current?.openDag(d)} />
      <div ref={clock} id="clock" className="hud" style={{ top: 18, left: "auto", right: "calc(var(--rail) + 24px)" }} />
      {view === "kanban" && (
        <Kanban hud={hud} moves={moves} constellation={(lane) => { choose("constellation"); renderer.current?.go([...BOARD, { kind: "state", id: lane }]); }} />
      )}
      <Rail hud={hud} view={view} />
      <div ref={tip} id="tip" />
      <div ref={panel} id="panel" />
    </>
  );
}

const CAP = 5;

/** One level in the navigator: a glyph sized by depth, its name, and its live count. */
function Node({ hud, path, label, count, size, flow, chev, open, onChev }: {
  hud: HudState; path: Path; label: string; count?: number; size: number; flow?: string;
  chev?: boolean; onChev?: () => void; open: (p: Path) => void;
}) {
  const key = pathKey(path), now = pathKey(hud.path);
  const on = now === key || now.startsWith(key + "/");
  // a lifecycle node glows while its machine is moving
  const cls = ["node", on && "on", now === key && "here", flow && hud.moving.includes(flow) && "live"].filter(Boolean).join(" ");
  return (
    <button className={cls} onClick={() => open(path)}>
      <i className="g" style={{ width: size, height: size }} />
      <span className="t">{label}</span>
      <span className="n">
        {onChev && (
          <span className="chev" onClick={(e) => { e.stopPropagation(); onChev(); }}>{chev ? "▾" : "▸"}</span>
        )}
        {count ?? ""}
      </span>
    </button>
  );
}

function Navigator({ hud, folded, view, choose, toggle, open, fly, openDag }: {
  hud: HudState; folded: boolean; view: ViewName; choose: (v: ViewName) => void; toggle: () => void; open: (p: Path) => void; fly: (group: string) => void; openDag: (dag: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [all, setAll] = useState<Set<string>>(new Set());
  const t = hud.tree, q = query.trim().toLowerCase();
  const flip = (s: Set<string>, id: string) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  };
  const statePath = (id: string): Path => [...BOARD, { kind: "state", id }];
  const props = { hud, open };
  let body = null;
  if (t && q) {
    // Filtering: a flat list of every level whose name matches, however deep.
    const hits = [
      ...hud.states.filter((s) => s.name.toLowerCase().includes(q)).map((s) => (
        <Node key={s.id} {...props} path={statePath(s.id)} label={s.name} count={s.count} size={10} />
      )),
      ...[...new Set([...Object.values(t.subs).flat(), ...Object.values(t.children).flat().map((c) => c.flow)])]
        .filter((m) => m.includes(q))
        .flatMap((m) => {
          const p = pathTo(t, m);
          return p ? [<Node key={m} {...props} path={p} label={m} count={hud.counts[m]} size={p.length > 3 ? 6 : 8} flow={m} />] : [];
        }),
      ...hud.dags.filter((d) => d.toLowerCase().includes(q)).map((d) => (
        <button key={`dag:${d}`} className="node" onClick={() => openDag(d)}>
          <i className="g" style={{ width: 7, height: 7 }} />
          <span className="t">{d}</span>
          <span className="n" />
        </button>
      )),
    ];
    body = (
      <div className="kids">
        <div className="lvl">Matches</div>
        {hits.length ? hits : <div className="lvl">no layer matches</div>}
      </div>
    );
  } else if (t) {
    const onPath = hud.path.map((l) => (l.kind === "machine" ? l.flow : ""));
    const live = (a: string, b: string) => (hud.counts[b] ?? 0) - (hud.counts[a] ?? 0);
    body = (
      <div className="kids">
        {hud.states.map((s) => {
          const sp = statePath(s.id), subs = [...(t.subs[s.id] ?? [])].sort(live);
          const here = pathKey(hud.path).startsWith(pathKey(sp));
          const isOpen = subs.length > 0 && (opened.has(s.id) || here);
          const shown = all.has(s.id) ? subs : subs.filter((m, i) => i < CAP || onPath.includes(m));
          return [
            <Node key={s.id} {...props} path={sp} label={s.name} count={s.count} size={subs.length ? 11 : 9}
              chev={isOpen} onChev={subs.length ? () => setOpened((o) => flip(o, s.id)) : undefined} />,
            isOpen && (
              <div key={`${s.id}:kids`} className="kids">
                {shown.map((m) => {
                  const mp: Path = [...sp, { kind: "machine", flow: m }];
                  const kids = onPath.includes(m) ? (t.children[m] ?? []) : [];
                  return [
                    <Node key={m} {...props} path={mp} label={m} count={hud.counts[m]} size={8} flow={m} />,
                    kids.length > 0 && (
                      <div key={`${m}:kids`} className="kids">
                        {kids.map((c) => (
                          <Node key={c.flow} {...props} path={[...mp, { kind: "machine", flow: c.flow }]} label={c.flow} count={hud.counts[c.flow]} size={6} flow={c.flow} />
                        ))}
                      </div>
                    ),
                  ];
                })}
                {shown.length < subs.length && (
                  <button className="more" onClick={() => setAll((a) => flip(a, s.id))}>+ {subs.length - shown.length} more lifecycle machines</button>
                )}
              </div>
            ),
          ];
        })}
      </div>
    );
  }
  return (
    <aside id="nav" className={folded ? "folded" : undefined}>
      <button id="fold" onClick={toggle} title={`${folded ? "Open" : "Fold"} the navigator ([)`} aria-label={folded ? "Open the navigator" : "Fold the navigator"} aria-expanded={!folded}>
        ‹
      </button>
      <section className="head">
        <h1>StarPulse</h1>
        <div className="sub"><span className={`dot ${hud.live}`} />{hud.stats}</div>
      </section>
      <section className="views">
        <h3>Views</h3>
        <button className={`node${view === "constellation" ? " on here" : ""}`} title="Constellation" onClick={() => (view === "constellation" ? open(BOARD) : choose("constellation"))}>
          <i className="g" style={{ width: 10, height: 10 }} />
          <span className="t">Constellation</span>
          <span className="n" />
        </button>
        <button className={`node${view === "kanban" ? " on here" : ""}`} title="Kanban" onClick={() => choose("kanban")}>
          <svg className="g kb-glyph" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="1" y="1" width="2.5" height="10" rx=".6" /><rect x="4.75" y="1" width="2.5" height="7" rx=".6" /><rect x="8.5" y="1" width="2.5" height="4.5" rx=".6" /></svg>
          <span className="t">Kanban</span>
          <span className="n">{hud.cards.length || ""}</span>
        </button>
      </section>
      {view === "kanban" && <section className="away note">Layers and Constellations belong to the Constellation view; they return when it is open.</section>}
      {view === "constellation" && <><section className="away">
        <input id="q" placeholder="filter layers…" autoComplete="off" value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setQuery("")} />
      </section>
      <section className="away layers">
        <h3>Layers</h3>
        <div id="layers">
          <Node {...props} path={BOARD} label="Board" count={hud.counts.board} size={14} flow="board" />
          {body}
        </div>
      </section>
      <section className="away">
        <h3>Constellations</h3>
        <div id="cons">
          {hud.groups.map((g) => (
            <button key={g.name} onClick={() => fly(g.name)}><i /><span>{g.name} · {g.n}</span></button>
          ))}
        </div>
      </section></>}
    </aside>
  );
}

function Rail({ hud, view }: { hud: HudState; view: ViewName }) {
  return (
    <aside id="rail">
      <section className="recent">
        <h3>Recent</h3>
        <div id="feed">
          {hud.feed.map((f) => (
            <div key={f.key + f.at}>
              <em>{f.time}</em> <b>{f.who}</b>{f.what && ` ${f.what}`} <em>{f.where}</em>
            </div>
          ))}
        </div>
      </section>
      <section id="legend">
        <h3>Legend</h3>
        {view === "kanban" ? (
          <>
            <span><i style={{ background: "#34d399" }} />checks pass</span><span><i style={{ background: "#fb7185" }} />failing</span><span><i style={{ background: "#fbbf24" }} />pending</span><br />
            <span><i style={{ background: "#a78bfa" }} />merged</span><span style={{ color: "#fbbf24" }}>⌁ n</span> review threads<br />
            <span><i style={{ background: "#a78bfa", boxShadow: "0 0 6px #a78bfa" }} />on a machine</span><span><i style={{ background: "#fbbf24", boxShadow: "0 0 6px #fbbf24" }} />moved now</span><br />
            <span style={{ color: "#fbbf24" }}>⧗ n</span> open dependencies
          </>
        ) : (
          <>
            <span><i style={{ background: "#c4b5fd" }} />deep</span><span><i style={{ background: "#67e8f9" }} />standard</span><span><i style={{ background: "#fde68a" }} />other</span><br />
            <span><i style={{ background: "#34d399" }} />ok</span><span><i style={{ background: "#fb7185" }} />failed</span>
            <span><i style={{ border: "1px solid #dbe4f3", background: "none", boxSizing: "border-box" }} />runnable</span><br />
            <span><i style={{ background: "#c084fc" }} />lifecycle machine</span><span><i style={{ background: "#fbbf24", boxShadow: "0 0 6px #fbbf24" }} />activity now</span>
          </>
        )}
      </section>
    </aside>
  );
}
