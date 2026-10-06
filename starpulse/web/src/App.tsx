// The page's DOM around the canvas: the left navigator, always shown and foldable to an icon strip,
// the right rail (actors, recent moves, legend), the clock, and the
// tooltip and panel the renderer fills. The canvas is the renderer's; this reads
// what it publishes and asks it to move.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Admin } from "./Admin";
import { AdminStore } from "./adminPrefs";
import { HistoryWindowStore } from "./historyWindow";
import { HudStore, useHud, type HudState } from "./hud";
import { BOARD, pathKey, type Path } from "./levels";
import { Kanban } from "./Kanban";
import { MoveStore, postMove } from "./move";
import { FoldStore, retired, viewOf, viewSearch, type ViewName } from "./nav";
import { renderer as makeRenderer, type Renderer } from "./renderer";
import { search, type Target } from "./search";
import { StartStore, fetchHarnesses, postStart } from "./start";

/** The actors the rail can hide, in the order it lists them. */

export function App() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const tip = useRef<HTMLDivElement>(null), panel = useRef<HTMLDivElement>(null), clock = useRef<HTMLDivElement>(null);
  const renderer = useRef<Renderer | null>(null);
  const [store] = useState(() => new HudStore());
  const hud = useHud(store);
  const [fold] = useState(() => new FoldStore());
  const [admin] = useState(() => new AdminStore());
  const [historyWindow] = useState(() => new HistoryWindowStore());
  // a move outlives the view that made it: the card stays where it landed while the writer answers
  const [moves] = useState(() => new MoveStore(postMove));
  // so does a started session: the card waits in In progress for its agent's claim whichever view is showing
  const [starts] = useState(() => new StartStore(postStart, moves));
  useEffect(() => void fetchHarnesses().then((h) => starts.load(h)), [starts]);
  const folded = useSyncExternalStore(fold.subscribe, fold.get);
  const prefs = useSyncExternalStore(admin.subscribe, admin.get);
  // a bare address opens the view the Admin chose; one that names a view opens that
  const [view, setView] = useState<ViewName>(() => viewOf(location.search, retired(location.pathname, location.hash) ? "constellation" : admin.get().view));
  // the view lives in the address, so a reload or a shared link opens the same one
  const choose = (v: ViewName) => {
    history.replaceState(null, "", `${location.pathname}${viewSearch(location.search, v, admin.get().view)}`);
    setView(v);
  };

  useEffect(() => {
    const els = { tip: tip.current!, panel: panel.current!, clock: clock.current! };
    const r = makeRenderer(canvas.current!, store, els, new URLSearchParams(location.search).has("demo"), admin.get);
    renderer.current = r;
    r.start();
    // times are written at the source, so a new clock is a new subtitle, feed and header clock
    const unsubscribe = admin.subscribe(() => r.refresh());
    return () => {
      unsubscribe();
      r.stop();
    };
  }, [store, admin]);
  // declared after the renderer's effect, so the first run already reaches it
  useEffect(() => {
    document.body.classList.toggle("kanban", view === "kanban");
    document.body.classList.toggle("admin", view === "admin");
    renderer.current?.show(view === "constellation");
    // the canvas was sized while hidden or behind the Kanban; refit it once it is the page again
    if (view === "constellation") renderer.current?.resize();
  }, [view]);

  // `[` folds the navigator from any view; the canvas already spans the page the fold frees, so nothing refits
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => fold.onKey(e);
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [fold]);

  return (
    <>
      <canvas ref={canvas} id="c" />
      <Navigator hud={hud} folded={folded} view={view} choose={choose} toggle={() => fold.toggle()} open={(p) => {
          choose("constellation");
          if (pathKey(p) === pathKey(hud.path)) renderer.current?.fitView();
          else renderer.current?.go(p);
        }}
        fly={(g) => renderer.current?.flyToGroup(g)} openDag={(d) => renderer.current?.openDag(d)}
        spot={(t) => renderer.current?.spot(t)} selectTask={(id) => renderer.current?.selectTask(id)} />
      <div ref={clock} id="clock" className="hud" style={{ top: 18, left: "auto", right: "calc(var(--rail) + 24px)" }} />
      {view === "admin" && <Admin store={admin} window={historyWindow} />}
      {view === "kanban" && (
        <Kanban hud={hud} moves={moves} starts={starts} compact={prefs.density === "compact"} constellation={(lane) => { choose("constellation"); renderer.current?.go([...BOARD, { kind: "state", id: lane }]); }} />
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

function Navigator({ hud, folded, view, choose, toggle, open, fly, openDag, spot, selectTask }: {
  hud: HudState; folded: boolean; view: ViewName; choose: (v: ViewName) => void; toggle: () => void; open: (p: Path) => void; fly: (group: string) => void; openDag: (dag: string) => void;
  spot: (target: Target | null) => void; selectTask: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const statePath = (id: string): Path => [...BOARD, { kind: "state", id }];
  // a click drills into a sun or a machine, opens a DAG's panel, or pins a task on the Board
  const pick = (target: Target) => {
    spot(null);
    if (target.kind === "state") open(statePath(target.id));
    else if (target.kind === "machine") open(target.path);
    else if (target.kind === "dag") openDag(target.name);
    else selectTask(target.id);
  };
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [all, setAll] = useState<Set<string>>(new Set());
  const t = hud.tree, q = query.trim().toLowerCase();
  const flip = (s: Set<string>, id: string) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  };
  const props = { hud, open };
  const hits = t && q ? search(q, { tree: t, states: hud.states, counts: hud.counts, dags: hud.dags, cards: hud.cards }) : [];
  let body = null;
  if (t && q) {
    // Searching: a flat list of every sun, machine, DAG and task the query names, however deep. Hovering one lights it on the canvas.
    body = (
      <div className="kids" onMouseLeave={() => spot(null)}>
        <div className="lvl">Matches</div>
        {hits.length ? hits.map((h) => {
          const key = `${h.target.kind}:${h.label}`, flow = h.target.kind === "machine" ? h.target.flow : undefined;
          const size = h.target.kind === "state" ? 10 : h.target.kind === "machine" ? (h.target.path.length > 3 ? 6 : 8) : h.target.kind === "dag" ? 7 : 5;
          return (
            <button key={key} data-kind={h.target.kind} className={`node hit${flow && hud.moving.includes(flow) ? " live" : ""}`} title={h.sub ?? h.label}
              onMouseEnter={() => spot(h.target)} onClick={() => pick(h.target)}>
              <i className="g" style={{ width: size, height: size }} />
              <span className="t">{h.label}{h.sub && <small>{h.sub}</small>}</span>
              <span className="n">{h.count ?? ""}</span>
            </button>
          );
        }) : <div className="lvl">nothing matches</div>}
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
        <button className={`node${view === "constellation" ? " on here" : ""}`} title="Star Map" onClick={() => (view === "constellation" ? open(BOARD) : choose("constellation"))}>
          <i className="g" style={{ width: 10, height: 10 }} />
          <span className="t">Star Map</span>
          <span className="n" />
        </button>
        <button className={`node${view === "kanban" ? " on here" : ""}`} title="Kanban" onClick={() => choose("kanban")}>
          <svg className="g kb-glyph" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="1" y="1" width="2.5" height="10" rx=".6" /><rect x="4.75" y="1" width="2.5" height="7" rx=".6" /><rect x="8.5" y="1" width="2.5" height="4.5" rx=".6" /></svg>
          <span className="t">Kanban</span>
          <span className="n">{hud.cards.length || ""}</span>
        </button>
      </section>
      {view === "kanban" && <section className="away note">Layers and DAGs belong to the Star Map view; they return when it is open.</section>}
      {view === "constellation" && <><section className="away">
        <input id="q" type="search" placeholder="search tasks, states, DAGs…" title="Search tasks, States, lifecycle machines and DAGs" aria-label="Search tasks, States, lifecycle machines and DAGs" autoComplete="off" value={query}
          onChange={(e) => { setQuery(e.target.value); spot(null); }}
          onKeyDown={(e) => {
            if (e.key === "Escape") { setQuery(""); spot(null); }
            // Enter takes the first match, as a click on it would
            if (e.key === "Enter" && hits[0]) pick(hits[0].target);
          }} />
      </section>
      <section className="away layers">
        <h3>Layers</h3>
        <div id="layers">
          <Node {...props} path={BOARD} label="Board" count={hud.counts.board} size={14} flow="board" />
          {body}
        </div>
      </section>
      <section className="away">
        <h3>DAGs</h3>
        <div id="cons">
          {hud.groups.map((g) => (
            <button key={g.name} onClick={() => fly(g.name)}><i /><span>{g.name} · {g.n}</span></button>
          ))}
        </div>
      </section></>}
      <section className="views admin-sec">
        <button className={`node${view === "admin" ? " on here" : ""}`} title="Admin" onClick={() => choose("admin")}>
          <svg className="g admin-glyph" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="1.8" /><path d="M6 .9v1.6M6 9.5v1.6M.9 6h1.6M9.5 6h1.6M2.4 2.4l1.1 1.1M8.5 8.5l1.1 1.1M2.4 9.6l1.1-1.1M8.5 3.5l1.1-1.1" /></svg>
          <span className="t">Admin</span>
          <span className="n" />
        </button>
      </section>
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
            <span><i style={{ background: "#a78bfa" }} />merged</span><span><span style={{ color: "#fbbf24" }}>⌁ n</span> review threads</span><br />
            <span><i style={{ background: "#a78bfa", boxShadow: "0 0 6px #a78bfa" }} />on a machine</span><span><i style={{ background: "#fbbf24", boxShadow: "0 0 6px #fbbf24" }} />moved now</span><br />
            <span><span style={{ color: "#fbbf24" }}>⧗ n</span> open dependencies</span><span><span style={{ color: "#fb923c" }}>⛓ n</span> Waiting tasks it holds</span><br />
            <span>hover a card:</span><span><i style={{ border: "1px solid #fb923c", background: "none", boxSizing: "border-box" }} />holds</span><span><i style={{ border: "1px solid #67e8f9", background: "none", boxSizing: "border-box" }} />waits on</span>
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
