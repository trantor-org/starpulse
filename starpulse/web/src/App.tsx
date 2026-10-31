// The page's DOM around the canvas: the left navigator, always open,
// the right rail (recent moves on top, the legend at the bottom), and the
// tooltip and panel the renderer fills. The canvas is the renderer's; this reads
// what it publishes and asks it to move.
import { lazy, Suspense, useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { NO_STARMAP_FILTERS, STARMAP_PREFS_KEY, useFilters } from "./shared/viewPrefs";
import { AdminStore } from "./features/admin/adminPrefs";
import { applyTheme } from "./features/admin/theme/apply";
import { ThemeStore } from "./features/admin/theme/themeStore";
import { HistoryWindowStore } from "./features/admin/historyWindow";
import { HudStore, type FeedLine, type HudState } from "./render/hud";
import { BOARD, pathKey, type Path } from "./render/levels";
import { Crumb } from "./features/level/Crumb";
import { DagLegend } from "./features/dags/DagLegend";
import { FeedLines, linesThatFit, Queues } from "./features/fanout/Fanout";
import { DagPressure } from "./features/dags/DagPressure";
import { Kept, revealKept } from "./shared/Kept";
import { SearchClear } from "./shared/SearchClear";
import { useScrollRest } from "./shared/scrollRest";
import { useBoardDrawn } from "./shared/boardDrawn";
import { Leaderboard } from "./features/kanban/Leaderboard";
import { recent } from "./features/kanban/kanbanModel";
import { MoveStore, postMove } from "./features/kanban/move";
import { AdminPage, Dags, Kanban, prefetchViews } from "./lazyViews";
import { onPhone, retired, shownView, viewOf, viewSearch, type ViewName } from "./shared/nav";
import { usePhone } from "./shared/usePhone";
import { renderer as makeRenderer } from "./render/renderer";
import type { Renderer } from "./render/rendererTypes";
import { booted } from "./boot";
import { search, type Target } from "./features/level/search";
import { StartStore, fetchHarnesses, postStart } from "./features/kanban/start";

/** The In Progress drill-in; loaded only when `?drill=TASK-N` opens it. */
const SunsDrillIn = lazy(() => import("./features/level/SunsDrillIn").then((m) => ({ default: m.SunsDrillIn })));

/** Keep page-wide React reconciliation outside the two-frame reveal and a rapid follow-up switch. */
const REVEAL_SETTLE_FRAMES = 8;

export function App() {
  // the page's entry starts the Board before this mounts and holds what it drew with; a page mounted on its own makes them here
  const [held] = useState(booted);
  const canvas = useRef<HTMLCanvasElement | null>(held?.canvas ?? null);
  const tip = useRef<HTMLDivElement | null>(held?.tip ?? null), panel = useRef<HTMLDivElement | null>(held?.panel ?? null);
  const renderer = useRef<Renderer | null>(held?.renderer ?? null);
  const [store] = useState(() => held?.store ?? new HudStore());
  const hud = useSyncExternalStore(store.subscribe, store.get);
  // the navigator and the rail fill after the Board's first frame: it needs their width, not their contents
  const shell = useBoardDrawn(hud.tree !== null);
  // the other views load once the Board is up, so the first switch to one finds it loaded
  const drawn = hud.tree !== null;
  useEffect(() => (drawn ? prefetchViews() : undefined), [drawn]);
  // once it is, the views not yet opened also mount hidden in the background, so a first switch to one only unhides it
  const [admin] = useState(() => held?.admin ?? new AdminStore());
  const [theme] = useState(() => held?.theme ?? new ThemeStore(applyTheme));
  const [historyWindow] = useState(() => new HistoryWindowStore());
  // a move outlives the view that made it: the card stays where it landed while the writer answers
  const [moves] = useState(() => new MoveStore(postMove));
  // so does a started session: the card waits in In progress for its agent's claim whichever view is showing
  const [starts] = useState(() => new StartStore(postStart, moves));
  useEffect(() => void fetchHarnesses().then((h) => starts.load(h)), [starts]);
  // a hovered Recent line lights its task on the view showing: the Kanban hears it as a task to spot and says why it has no card
  const [line, setLine] = useState<string | null>(null), [spotted, setSpotted] = useState<string | null>(null);
  const [why, setWhy] = useState<string | null>(null), [opening, setOpening] = useState<{ id: string } | null>(null);
  // and a DAG-finished line lights its row in the Jobs view and opens its modal
  const [spottedDag, setSpottedDag] = useState<string | null>(null), [openingDag, setOpeningDag] = useState<{ name: string } | null>(null);
  // the Kanban's text search draws in the navigator's search slot
  const [searchSlot, setSearchSlot] = useState<HTMLElement | null>(null);
  // and the Jobs view's filter draws in the same section, above the run-pressure cards
  const [dgSlot, setDgSlot] = useState<HTMLElement | null>(null);
  // and its milestone outline draws in the outline slot below it, where Layers draw on the Star Map
  const [outlineSlot, setOutlineSlot] = useState<HTMLElement | null>(null);
  const prefs = useSyncExternalStore(admin.subscribe, admin.get);
  // a bare address opens the view the Admin chose; one that names a view opens that
  const [chosen, setView] = useState<ViewName>(() => viewOf(location.search, retired(location.pathname, location.hash) ? "constellation" : admin.get().view));
  // the Star Map is desktop-only: a phone width shows the Kanban in its place, and widening the page returns to what was chosen
  const phone = usePhone();
  const view = shownView(chosen, phone);
  const activeView = useRef(view);
  const pendingView = useRef(0);
  const commitView = useCallback((next: ViewName, url: string) => {
    cancelAnimationFrame(pendingView.current);
    let frames = REVEAL_SETTLE_FRAMES;
    const frame = () => {
      if (frames-- > 1) return void (pendingView.current = requestAnimationFrame(frame));
      history.replaceState(null, "", url);
      setView(next);
    };
    pendingView.current = requestAnimationFrame(frame);
  }, []);
  const reveal = useCallback((next: ViewName, settled = false) => {
    const mounted = revealKept(next === "constellation" ? null : next);
    if (!mounted) return false;
    const off = next !== "constellation";
    canvas.current?.classList.toggle("off", off);
    // Hiding chrome must accompany a view that covers the map. Restoring idle chrome can wait for React ownership,
    // leaving the measured Star Map reveal to composite only the canvas and the outgoing kept surface.
    if (off || settled) {
      tip.current?.classList.toggle("off", off);
      panel.current?.classList.toggle("off", off);
      document.getElementById("crumb")?.classList.toggle("off", off);
    }
    if (off) renderer.current?.show(false);
    return true;
  }, []);
  // the view lives in the address, so a reload or a shared link opens the same one
  const choose = useCallback((target: ViewName) => {
    const v = shownView(target, onPhone());
    const url = `${location.pathname}${viewSearch(location.search, v, admin.get().view)}`;
    activeView.current = v;
    cancelAnimationFrame(pendingView.current);
    if (!reveal(v)) {
      history.replaceState(null, "", url);
      return void setView(v);
    }
    // The mounted surface changes now; page-wide React bookkeeping follows after the measured reveal frames.
    commitView(v, url);
  }, [admin, commitView, reveal]);
  useEffect(() => () => cancelAnimationFrame(pendingView.current), []);
  const [drill, setDrill] = useState(() => new URLSearchParams(location.search).get("drill"));
  const closeDrill = () => {
    const q = new URLSearchParams(location.search);
    q.delete("drill");
    history.replaceState(null, "", `${location.pathname}${q.size ? `?${q}` : ""}${location.hash}`);
    setDrill(null);
  };
  // stable, so a stream event that changes nothing the Kanban shows does not draw it again
  const flyToLane = useCallback((lane: string) => { choose("constellation"); renderer.current?.go([...BOARD, { kind: "state", id: lane }]); }, [choose]);

  useEffect(() => {
    // a booted renderer outlives the page's tree: it was started before this mounted and is never stopped by it
    const r = held?.renderer ?? makeRenderer(canvas.current!, store, { tip: tip.current!, panel: panel.current! }, new URLSearchParams(location.search).has("demo"), admin.get);
    renderer.current = r;
    if (!held) r.start();
    // times are written at the source, so a new clock is a new subtitle and feed
    const unsubscribe = admin.subscribe(() => r.refresh());
    return () => {
      unsubscribe();
      if (!held) r.stop();
    };
  }, [held, store, admin]);
  // declared after the renderer's effect, so the first run already reaches it
  useEffect(() => {
    activeView.current = view;
    reveal(view, true);
    renderer.current?.show(view === "constellation");
  }, [view, reveal]);

  // a level from the navigator's search or the breadcrumb opens on the Star Map, refitted when it is already the one shown
  const open = (p: Path) => {
    choose("constellation");
    if (pathKey(p) === pathKey(hud.path)) renderer.current?.fitView();
    else renderer.current?.go(p);
  };

  return (
    <>
      {!held && <canvas ref={canvas} id="c" />}
      <Navigator shell={shell} hud={hud} view={view} phone={phone} activeView={activeView} slot={setSearchSlot} dgSlot={setDgSlot} outlineSlot={setOutlineSlot} choose={choose} open={open}
        spot={(t) => renderer.current?.spot(t)} selectTask={(id) => renderer.current?.selectTask(id)} />
      <Crumb path={hud.path} states={hud.states} sources={hud.tree?.sources} open={open} off={view !== "constellation"} />
      {view === "constellation" && hud.tree !== null && hud.cards.length === 0 && hud.capabilities?.create && (
        <section id="first-run" aria-label="Get started">
          <strong>No tasks yet.</strong> Create one:
          <code>uvx starpulse task create "My first task"</code>
          <span>An agent usually runs the CLI; you can too, or use New task on the Kanban.</span>
        </section>
      )}
      {/* views warm in this order, the Kanban first: it is the one most often opened */}
      <Kept name="kanban" on={view === "kanban"} warm={drawn}>
        <Suspense fallback={null}>
          <Kanban hud={hud} moves={moves} starts={starts} compact={prefs.density === "compact"} searchSlot={searchSlot} outlineSlot={outlineSlot} constellation={flyToLane}
            spot={spotted} note={setWhy} opening={opening} records={held?.records} />
        </Suspense>
      </Kept>
      <Kept name="jobs" on={view === "jobs"} warm={drawn}><Suspense fallback={null}><Dags data={hud.dagData} openPath={open} spot={spottedDag} opening={openingDag} filterSlot={dgSlot} /></Suspense></Kept>
      <Kept name="admin" on={view === "admin"} warm={drawn}><Suspense fallback={null}><AdminPage store={admin} theme={theme} window={historyWindow} hint={hud.hint} /></Suspense></Kept>
      <Rail shown={shell} hud={hud} view={view} note={view === "kanban" && line && why ? { key: line, text: why } : null}
        can={(l) => (view === "kanban" ? !!l.task : view === "jobs" ? !!l.dag : view === "constellation" && !!l.task)}
        spot={(l) => {
          setLine(l?.key ?? null);
          if (view === "kanban") return setSpotted(l?.task ?? null);
          if (view === "jobs") return setSpottedDag(l?.dag ?? null);
          const lane = (id: string) => hud.cards.find((c) => c.id === id)?.lane ?? "";
          renderer.current?.spot(l?.task ? { kind: "task", id: l.task, lane: lane(l.task) } : null, true);
        }}
        pick={(l) => {
          if (view === "kanban") setOpening({ id: l.task! });
          else if (view === "jobs") setOpeningDag({ name: l.dag! });
          else renderer.current?.openTask(l.task!);
        }} />
      {!held && <div ref={tip} id="tip" />}
      {!held && <div ref={panel} id="panel" />}
      {drill && <Suspense fallback={null}><SunsDrillIn tasks={hud.cards} roles={hud.roles} task={drill} dags={hud.dags.length} onClose={closeDrill} /></Suspense>}
    </>
  );
}

/** The navigator's frame is always there (the canvas starts at its edge); `shell` fills it. */
function Navigator({ shell, ...props }: { shell: boolean } & Parameters<typeof NavigatorBody>[0]) {
  const nav = useRef<HTMLElement>(null);
  // a scrolling Matches list stands its rows aside, so those passing under a still pointer light nothing on the canvas
  useScrollRest(nav, ".matches");
  // phone width: the navigator is hidden until the bar's More opens it as a sheet over the view; choosing a view or a search hit closes it
  const [sheet, setSheet] = useState(false);
  const shut = <A extends unknown[]>(fn: (...a: A) => void) => (...a: A) => { setSheet(false); fn(...a); };
  useEffect(() => {
    if (!sheet) return;
    const key = (e: KeyboardEvent) => e.key === "Escape" && setSheet(false);
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, [sheet]);
  // the Star Map's canvas ends above the bar and leaves its height from the first frame; it fits again whenever the text size resizes the bar
  const bar = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = bar.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    // a page wider than the phone never draws the bar, so its height stays 0 and the renderer's own fit stands
    let fitted = 0;
    const watch = new ResizeObserver(() => {
      if (el.offsetHeight === fitted) return;
      fitted = el.offsetHeight;
      dispatchEvent(new Event("resize"));
    });
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const { view, activeView, choose, open } = props;
  const tab = (v: ViewName, label: string, glyph: ReactNode, off = false) => (
    <button className={view === v ? "on" : undefined} aria-current={view === v ? "page" : undefined} title={off ? `${label} is desktop-only` : label} disabled={off}
      onClick={() => (v === "constellation" && activeView.current === v ? open(BOARD) : choose(v))}>{glyph}<span>{label}</span></button>
  );
  return (
    <>
      <aside id="nav" ref={nav} className={sheet ? "sheet" : undefined}>
        {shell && <NavigatorBody {...props} choose={shut(choose)} open={shut(open)} selectTask={shut(props.selectTask)} />}
        <button className="pn-x" aria-label="Close the navigator" onClick={() => setSheet(false)}>✕</button>
      </aside>
      {sheet && <div id="pn-scrim" onClick={() => setSheet(false)} />}
      {/* phone width: the bar along the bottom edge is the view switcher, since the navigator is hidden there */}
      <nav id="pnav" ref={bar} aria-label="Views">
        {tab("constellation", "Star Map", <svg className="g" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="5" fill="currentColor" stroke="none" /><ellipse cx="12" cy="12" rx="10.6" ry="3.9" transform="rotate(-28 12 12)" strokeWidth="1.5" /><circle cx="20.6" cy="3.6" r="1.1" fill="currentColor" stroke="none" /></svg>, props.phone)}
        {tab("kanban", "Kanban", <svg className="g kb" width="14" height="14" viewBox="0 0 12 12" aria-hidden="true"><rect x="1" y="1" width="2.5" height="10" rx=".6" /><rect x="4.75" y="1" width="2.5" height="7" rx=".6" /><rect x="8.5" y="1" width="2.5" height="4.5" rx=".6" /></svg>)}
        {tab("jobs", "Jobs", <svg className="g dg" width="14" height="14" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 9.5 5 3.2 8.6 5.4 10.4 2" /><circle cx="2" cy="9.5" r="1.3" /><circle cx="5" cy="3.2" r="1.3" /><circle cx="8.6" cy="5.4" r="1.1" /><circle cx="10.4" cy="2" r=".9" /></svg>)}
        {tab("admin", "Admin", <svg className="g" width="14" height="14" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="1.8" /><path d="M6 .9v1.6M6 9.5v1.6M.9 6h1.6M9.5 6h1.6M2.4 2.4l1.1 1.1M8.5 8.5l1.1 1.1M2.4 9.6l1.1-1.1M8.5 3.5l1.1-1.1" /></svg>)}
        <button className="more" aria-label="More: search, status and the rest of the navigator" aria-expanded={sheet} onClick={() => setSheet(true)}><svg className="g" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" /></svg><span>More</span><i className={`dot ${props.hud.live}`} /></button>
      </nav>
    </>
  );
}

function NavigatorBody({ hud, view, phone, activeView, slot, dgSlot, outlineSlot, choose, open, spot, selectTask }: {
  hud: HudState; view: ViewName; phone: boolean; activeView: { current: ViewName }; slot: (el: HTMLElement | null) => void; dgSlot: (el: HTMLElement | null) => void; outlineSlot: (el: HTMLElement | null) => void; choose: (v: ViewName) => void; open: (p: Path) => void;
  spot: (target: Target | null) => void; selectTask: (id: string) => void;
}) {
  const [{ query }, keep] = useFilters(STARMAP_PREFS_KEY, NO_STARMAP_FILTERS), setQuery = (v: string) => keep({ query: v });
  // the Leaderboard's ages move by the minute
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now() / 1000), 30_000);
    return () => clearInterval(tick);
  }, []);
  const searchBox = useRef<HTMLInputElement>(null);
  const statePath = (id: string): Path => [...BOARD, { kind: "state", id }];
  // a click drills into a sun or a machine, or pins a task on the Board
  const pick = (target: Target) => {
    spot(null);
    if (target.kind === "state") open(statePath(target.id));
    else if (target.kind === "machine") open(target.path);
    else selectTask(target.id);
  };
  const t = hud.tree, q = query.trim().toLowerCase();
  const hits = t && q ? search(q, { tree: t, states: hud.states, counts: hud.counts, hostCounts: hud.hostCounts, cards: hud.cards }) : [];
  let body = null;
  if (t && q) {
    // Searching: a flat list of every sun, machine and task the query names, however deep. Hovering one lights it on the canvas.
    body = (
      <div className="kids" onMouseLeave={() => spot(null)}>
        <div className="lvl">Matches</div>
        {hits.length ? hits.map((h) => {
          const key = `${h.target.kind}:${h.label}:${h.sub ?? ""}`, flow = h.target.kind === "machine" ? h.target.flow : undefined;
          const size = h.target.kind === "state" ? 10 : h.target.kind === "machine" ? (h.target.path.length > 3 ? 6 : 8) : 5;
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
    <>
      <section className="head">
        <h1>StarPulse</h1>
        <div className="sub"><span className={`dot ${hud.live}`} />{hud.note || hud.stats}</div>
      </section>
      <section className="views">
        <h3>Views</h3>
        <button className={`node${view === "constellation" ? " on here" : ""}`} title={phone ? "Star Map is desktop-only" : "Star Map"} disabled={phone} onClick={() => (activeView.current === "constellation" ? open(BOARD) : choose("constellation"))}>
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
          <span className="n">{recent(hud.cards, now, hud.roles).length || ""}</span>
        </button>
        <button className={`node${view === "jobs" ? " on here" : ""}`} title="Jobs" onClick={() => choose("jobs")}>
          <svg className="g dg-glyph" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 9.5 5 3.2 8.6 5.4 10.4 2" /><circle cx="2" cy="9.5" r="1.3" /><circle cx="5" cy="3.2" r="1.3" /><circle cx="8.6" cy="5.4" r="1.1" /><circle cx="10.4" cy="2" r=".9" /></svg>
          <span className="t">Jobs</span>
          <span className="n">{hud.dags.length || ""}</span>
        </button>
      </section>
      {view !== "admin" && (
        <section className="away has-x search">
          {view === "kanban" ? <div key="kb" ref={slot} /> : view === "jobs" ? <div key="dg" ref={dgSlot} /> : <>
            <input id="q" ref={searchBox} type="search" placeholder="search…" title="Search tasks, States and lifecycle machines" aria-label="Search tasks, States and lifecycle machines" autoComplete="off" value={query}
              onChange={(e) => { setQuery(e.target.value); spot(null); }}
              onKeyDown={(e) => {
                if (e.key === "Escape") { setQuery(""); spot(null); }
                // Enter takes the first match, as a click on it would
                if (e.key === "Enter" && hits[0]) pick(hits[0].target);
              }} />
            <SearchClear input={searchBox} value={query} clear={() => { setQuery(""); spot(null); }} />
          </>}
        </section>
      )}
      {view === "kanban" && <section className="away outline" ref={outlineSlot} />}
      {view === "jobs" && <><Queues pools={hud.pools} /><DagPressure data={hud.dagData} /></>}
      {view === "constellation" && (body ? <section className="away matches">{body}</section> : <Leaderboard tasks={hud.cards} roles={hud.roles} now={now} open={selectTask} />)}
      <section className="views admin-sec">
        <button className={`node${view === "admin" ? " on here" : ""}`} title="Admin" onClick={() => choose("admin")}>
          <svg className="g admin-glyph" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="1.8" /><path d="M6 .9v1.6M6 9.5v1.6M.9 6h1.6M9.5 6h1.6M2.4 2.4l1.1 1.1M8.5 8.5l1.1 1.1M2.4 9.6l1.1-1.1M8.5 3.5l1.1-1.1" /></svg>
          <span className="t">Admin</span>
          <span className="n" />
        </button>
      </section>
    </>
  );
}

/** The right rail, the same order in every view: the recent events at the top, the legend at the bottom. */
export function Rail({ shown = true, ...body }: { shown?: boolean } & Parameters<typeof RailBody>[0]) {
  // the frame is always there (the canvas ends at its edge); `shown` fills it
  return <aside id="rail">{shown && <RailBody {...body} />}</aside>;
}

function RailBody({ hud, view, ...feed }: { hud: HudState; view: ViewName } & Omit<Parameters<typeof FeedLines>[0], "lines">) {
  // the lines hold still under the pointer, so a run starting mid-aim doesn't push the next line under the click
  const [held, setHeld] = useState<FeedLine[] | null>(null);
  // the feed is a fixed box: it keeps only the newest lines it shows whole, and grows no scrollbar
  const box = useRef<HTMLDivElement>(null), [fit, setFit] = useState(Infinity);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => setFit(linesThatFit(el.clientHeight, parseFloat(getComputedStyle(el).lineHeight)));
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    measure();
    return () => watch.disconnect();
  }, []);
  return (
    <>
      <section className="recent">
        <h3>Recent</h3>
        <div id="feed" ref={box} onPointerEnter={() => setHeld(hud.feed)} onPointerLeave={() => setHeld(null)}>
          <FeedLines lines={(held ?? hud.feed).slice(0, fit)} {...feed} />
        </div>
      </section>
      <section id="legend">
        <h3>Legend</h3>
        {view === "jobs" ? <DagLegend /> : view === "kanban" ? (
          <>
            <span><i style={{ background: "var(--ok)" }} />checks pass</span><span><i style={{ background: "var(--fail)" }} />failing</span><span><i style={{ background: "var(--run)" }} />pending</span><br />
            <span><i style={{ background: "var(--agent)" }} />merged</span><span><span style={{ color: "var(--run)" }}>⌁ n</span> review threads</span><br />
            <span><i style={{ background: "var(--agent)", boxShadow: "0 0 6px var(--agent)" }} />on a machine</span><span><i style={{ background: "var(--ready)", boxShadow: "0 0 6px var(--ready)" }} />on a mapped machine</span><span><i style={{ background: "var(--run)", boxShadow: "0 0 6px var(--run)" }} />moved now</span><br />
            <span><span style={{ color: "var(--run)" }}>⧗ n</span> open dependencies</span><span><span style={{ color: "var(--hold)" }}>⛓ n</span> Waiting tasks it holds</span><br />
            <span>hover a card:</span><span><i style={{ border: "1px solid var(--hold)", background: "none", boxSizing: "border-box" }} />holds</span><span><i style={{ border: "1px solid var(--waits)", background: "none", boxSizing: "border-box" }} />waits on</span>
          </>
        ) : (
          <>
            <span><i style={{ background: "var(--agent-text)" }} />deep</span><span><i style={{ background: "var(--waits)" }} />standard</span><span><i style={{ background: "var(--run-text)" }} />other</span><br />
            <span><i style={{ background: "color-mix(in oklch, var(--agent) 85%, var(--fail))" }} />lifecycle machine</span><span className="mapleg"><i />mapped machine</span><span><i style={{ background: "var(--run)", boxShadow: "0 0 6px var(--run)" }} />activity now</span>
          </>
        )}
      </section>
    </>
  );
}
