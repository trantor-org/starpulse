// The page's DOM around the canvas: the left navigator, always shown and foldable to an icon strip,
// the right rail (recent moves on top, the legend at the bottom), the clock, and the
// tooltip and panel the renderer fills. The canvas is the renderer's; this reads
// what it publishes and asks it to move.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Admin } from "./Admin";
import { AdminStore } from "./adminPrefs";
import { ForwardingStore } from "./forwarding";
import { HistoryWindowStore } from "./historyWindow";
import { HudStore, useHud, type FeedLine, type HudState } from "./hud";
import { LevelStore } from "./levelData";
import { BOARD, pathKey, type Path } from "./levels";
import { Crumb } from "./Crumb";
import { Dags, DagLegend } from "./Dags";
import { FeedLines, Queues } from "./Fanout";
import { SearchClear } from "./SearchClear";
import { Kanban } from "./Kanban";
import { MoveStore, postMove } from "./move";
import { OrbitCard } from "./OrbitCard";
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
  const [forwarding] = useState(() => new ForwardingStore());
  // the level above the Board: asked for once and then every minute, and its navigator entry shown only when the server has one
  const [levels] = useState(() => new LevelStore());
  useEffect(() => {
    void levels.refresh();
    return () => levels.dispose();
  }, [levels]);
  const level = useSyncExternalStore(levels.subscribe, levels.get);
  // a move outlives the view that made it: the card stays where it landed while the writer answers
  const [moves] = useState(() => new MoveStore(postMove));
  // so does a started session: the card waits in In progress for its agent's claim whichever view is showing
  const [starts] = useState(() => new StartStore(postStart, moves));
  useEffect(() => void fetchHarnesses().then((h) => starts.load(h)), [starts]);
  // a hovered Recent line lights its task on the view showing: the Kanban hears it as a task to spot and says why it has no card
  const [line, setLine] = useState<string | null>(null), [spotted, setSpotted] = useState<string | null>(null);
  const [why, setWhy] = useState<string | null>(null), [opening, setOpening] = useState<{ id: string } | null>(null);
  const folded = useSyncExternalStore(fold.subscribe, fold.get);
  // the Kanban's text search draws in the navigator's search slot and reports what it holds, for the folded strip's magnifier
  const [searchSlot, setSearchSlot] = useState<HTMLElement | null>(null);
  // and its milestone outline draws in the outline slot below it, where Layers draw on the Star Map
  const [outlineSlot, setOutlineSlot] = useState<HTMLElement | null>(null);
  const [kanbanQuery, setKanbanQuery] = useState("");
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
    document.body.classList.toggle("dags", view === "dags");
    document.body.classList.toggle("admin", view === "admin");
    document.body.classList.toggle("graph", view === "graph");
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

  // a level from the navigator's search or the breadcrumb opens on the Star Map, refitted when it is already the one shown
  const open = (p: Path) => {
    choose("constellation");
    if (pathKey(p) === pathKey(hud.path)) renderer.current?.fitView();
    else renderer.current?.go(p);
  };

  return (
    <>
      <canvas ref={canvas} id="c" />
      <Navigator hud={hud} folded={folded} view={view} slot={setSearchSlot} outlineSlot={setOutlineSlot} kanbanQuery={kanbanQuery} choose={choose} hasLevel={view === "graph" || (level.kind !== "none" && level.kind !== "loading")} toggle={() => fold.toggle()} open={open}
        fly={(g) => renderer.current?.flyToGroup(g)} openDag={(d) => renderer.current?.openDag(d)}
        spot={(t) => renderer.current?.spot(t)} selectTask={(id) => renderer.current?.selectTask(id)} />
      {view === "constellation" && <Crumb path={hud.path} states={hud.states} open={open} />}
      <div ref={clock} id="clock" className="hud" style={{ top: 18, left: "auto", right: "calc(var(--rail) + 24px)" }} />
      {view === "admin" && <Admin store={admin} window={historyWindow} forwarding={forwarding} />}
      {view === "graph" && (
        <OrbitCard state={level} retry={() => void levels.refresh()} motion={prefs.motion} names={hud.names} />
      )}
      {view === "kanban" && (
        <Kanban hud={hud} moves={moves} starts={starts} compact={prefs.density === "compact"} searchSlot={searchSlot} outlineSlot={outlineSlot} onQuery={setKanbanQuery} constellation={(lane) => { choose("constellation"); renderer.current?.go([...BOARD, { kind: "state", id: lane }]); }}
          spot={spotted} note={setWhy} opening={opening} />
      )}
      {view === "dags" && <Dags data={hud.dagData} />}
      <Rail hud={hud} view={view} note={view === "kanban" && line && why ? { key: line, text: why } : null}
        can={(l) => (view === "kanban" ? !!l.task : view === "constellation" && !!(l.task || l.dag))}
        spot={(l) => {
          setLine(l?.key ?? null);
          if (view === "kanban") return setSpotted(l?.task ?? null);
          const lane = (id: string) => hud.cards.find((c) => c.id === id)?.lane ?? "";
          renderer.current?.spot(!l ? null : l.task ? { kind: "task", id: l.task, lane: lane(l.task) } : { kind: "dag", name: l.dag! }, true);
        }}
        pick={(l) => {
          if (view === "kanban") setOpening({ id: l.task! });
          else if (l.task) renderer.current?.openTask(l.task);
          else renderer.current?.openDag(l.dag!);
        }} />
      <div ref={tip} id="tip" />
      <div ref={panel} id="panel" />
    </>
  );
}

/** The folded strip's search button, at the search's height: lit with a dot while the active view's search holds a query. It sits in the search's section, so only the folded strip shows it. */
function SearchMagnifier({ view, query, open }: { view: ViewName; query: string; open: () => void }) {
  const name = view === "kanban" ? "Kanban" : "Star Map";
  return (
    <button type="button" id="nv-mag" className={query ? "set" : undefined} aria-label="Search" title={`Search the ${name}${query ? ` (filtering: ${query})` : ""}`} onClick={open}>
      <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
        <circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M15.4 15.4 L21 21" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      </svg>
    </button>
  );
}

function Navigator({ hud, folded, view, slot, outlineSlot, kanbanQuery, choose, hasLevel, toggle, open, fly, openDag, spot, selectTask }: {
  hud: HudState; folded: boolean; view: ViewName; slot: (el: HTMLElement | null) => void; outlineSlot: (el: HTMLElement | null) => void; kanbanQuery: string; choose: (v: ViewName) => void; hasLevel: boolean; toggle: () => void; open: (p: Path) => void; fly: (group: string) => void; openDag: (dag: string) => void;
  spot: (target: Target | null) => void; selectTask: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const searchBox = useRef<HTMLInputElement>(null);
  // the folded strip's magnifier unfolds the panel, then the active view's search takes the focus once it is shown
  const searchHost = useRef<HTMLElement>(null);
  const focusSearch = useRef(false);
  useEffect(() => {
    if (!focusSearch.current || folded) return;
    focusSearch.current = false;
    searchHost.current?.querySelector("input")?.focus();
  }, [folded]);
  const statePath = (id: string): Path => [...BOARD, { kind: "state", id }];
  // a click drills into a sun or a machine, opens a DAG's panel, or pins a task on the Board
  const pick = (target: Target) => {
    spot(null);
    if (target.kind === "state") open(statePath(target.id));
    else if (target.kind === "machine") open(target.path);
    else if (target.kind === "dag") openDag(target.name);
    else selectTask(target.id);
  };
  const t = hud.tree, q = query.trim().toLowerCase();
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
          <i className="g orbit">
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <circle cx="12" cy="12" r="5" fill="currentColor" />
              <ellipse cx="12" cy="12" rx="10.6" ry="3.9" transform="rotate(-28 12 12)" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <circle cx="20.6" cy="3.6" r="1.1" fill="currentColor" />
            </svg>
          </i>
          <span className="t">Star Map</span>
          <span className="n" />
        </button>
        <button className={`node${view === "kanban" ? " on here" : ""}`} title="Kanban" onClick={() => choose("kanban")}>
          <svg className="g kb-glyph" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="1" y="1" width="2.5" height="10" rx=".6" /><rect x="4.75" y="1" width="2.5" height="7" rx=".6" /><rect x="8.5" y="1" width="2.5" height="4.5" rx=".6" /></svg>
          <span className="t">Kanban</span>
          <span className="n">{hud.cards.length || ""}</span>
        </button>
        <button className={`node${view === "dags" ? " on here" : ""}`} title="DAGs" onClick={() => choose("dags")}>
          <svg className="g dg-glyph" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 9.5 5 3.2 8.6 5.4 10.4 2" /><circle cx="2" cy="9.5" r="1.3" /><circle cx="5" cy="3.2" r="1.3" /><circle cx="8.6" cy="5.4" r="1.1" /><circle cx="10.4" cy="2" r=".9" /></svg>
          <span className="t">DAGs</span>
          <span className="n">{hud.dags.length || ""}</span>
        </button>
        {hasLevel && (
          <button className={`node${view === "graph" ? " on here" : ""}`} title="Flow graph: the level above the Board" onClick={() => choose("graph")}>
            <svg className="g og-glyph" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><ellipse cx="6" cy="6" rx="5" ry="2.4" /><circle cx="6" cy="6" r="1.2" /></svg>
            <span className="t">Flow graph</span>
            <span className="n" />
          </button>
        )}
      </section>
      {view !== "admin" && view !== "graph" && view !== "dags" && (
        <section className="away has-x search" ref={searchHost}>
          {view === "kanban" ? <div ref={slot} /> : <>
            <input id="q" ref={searchBox} type="search" placeholder="search…" title="Search tasks, States, lifecycle machines and DAGs" aria-label="Search tasks, States, lifecycle machines and DAGs" autoComplete="off" value={query}
              onChange={(e) => { setQuery(e.target.value); spot(null); }}
              onKeyDown={(e) => {
                if (e.key === "Escape") { setQuery(""); spot(null); }
                // Enter takes the first match, as a click on it would
                if (e.key === "Enter" && hits[0]) pick(hits[0].target);
              }} />
            <SearchClear input={searchBox} value={query} clear={() => { setQuery(""); spot(null); }} />
          </>}
          <SearchMagnifier view={view} query={view === "kanban" ? kanbanQuery : query} open={() => { if (folded) { focusSearch.current = true; toggle(); } else searchHost.current?.querySelector("input")?.focus(); }} />
        </section>
      )}
      {view === "kanban" && <section className="away outline" ref={outlineSlot} />}
      {view === "graph" && <section className="away note">Layers and DAGs belong to the Star Map view; they return when it is open.</section>}
      {view === "dags" && <><section className="away note">Layers belong to the Star Map view; they return when it is open.</section><Queues pools={hud.pools} /></>}
      {view === "constellation" && <>
      {body && <section className="away matches">{body}</section>}
      <section className="away">
        <h3>DAGs</h3>
        <div id="cons">
          {hud.groups.map((g) => (
            <button key={g.name} onClick={() => fly(g.name)}><i /><span>{g.name} · {g.n}</span></button>
          ))}
        </div>
      </section>
      <Queues pools={hud.pools} /></>}
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

/** The right rail, the same order in every view: the recent events at the top, the legend at the bottom. */
export function Rail({ hud, view, ...feed }: { hud: HudState; view: ViewName } & Omit<Parameters<typeof FeedLines>[0], "lines">) {
  // the lines hold still under the pointer, so a run starting mid-aim doesn't push the next line under the click
  const [held, setHeld] = useState<FeedLine[] | null>(null);
  return (
    <aside id="rail">
      <section className="recent">
        <h3>Recent</h3>
        <div id="feed" onPointerEnter={() => setHeld(hud.feed)} onPointerLeave={() => setHeld(null)}>
          <FeedLines lines={held ?? hud.feed} {...feed} />
        </div>
      </section>
      <section id="legend">
        <h3>Legend</h3>
        {view === "dags" ? <DagLegend /> : view === "graph" ? (
          <>
            <span><i style={{ background: "#a78bfa" }} />source: a planet on its own orbit</span><br />
            <span><i style={{ border: "1px dashed #94a3b8", background: "none", boxSizing: "border-box" }} />unattributed: no Board of its own</span><br />
            <span><i style={{ background: "#fb7185", boxShadow: "0 0 6px #fb7185" }} />comet: a replayed arrival</span><br />
            <span><i style={{ background: "#34d399" }} />hover a body for its numbers, click or Tab for its details</span>
          </>
        ) : view === "kanban" ? (
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
