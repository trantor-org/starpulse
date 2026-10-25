// The canvas side of the page, ported from the approved round-13 mockup
// (the design mockup): it takes the Board and the runs instances from the
// server's event stream (every machine's tasks and the runs instances' workflows), merges them into one sky,
// lays the current level out with scene.ts, plays each move once as the
// mockup's replay did, and owns the level stack, the view, the tooltip and the
// click panels. It draws only while something animates (idle.ts).
// Click drills in, right-click steps out (after clearing any zoom), the wheel
// zooms about the cursor between the level's fit and eight times it, and a drag
// pans only while zoomed in. The path and each level's zoom are kept per browser.
import { apiFetch } from "../api/apiFetch";
import { embedded } from "../demo/host";
import { RunEvents } from "../features/fanout/fanoutModel";
import type { FeedLine, HudState, HudStore } from "./hud";
import { DAG_COLOR, drawing, ease, easeO, type DrawCtx, type Hover, type LTask } from "./draw";
import { animating, frameLoop, framePace } from "./idle";
import { BOARD, hostOf, pathKey, pathLedger, pathTo, startPath, taskKicker, topFlow, type Level, type Path } from "./levels";
import { optionalSteps } from "../features/level/ledger";
import type { DoctorBox, PanelCtx } from "../features/level/ledgerPanel";
type LedgerPanel = typeof import("../features/level/ledgerPanel");
let ledgerPanel: LedgerPanel | null = null;
let ledgerPanelP: Promise<LedgerPanel> | undefined;
const loadLedgerPanel = (): Promise<LedgerPanel> => (ledgerPanelP ??= import("../features/level/ledgerPanel").then((m) => (ledgerPanel = m)));
import { createContract } from "../features/level/contract";
import { type Hits } from "../features/level/ledgerRows";
import { dragMove, dragStart, keyScroll, wheelScroll } from "../features/level/ledgerScroll";
import { RerunStore } from "../features/level/rerun";
import { spotIn, type Target } from "../features/level/search";
import {
  RAMP, TAU, bez, build, curveDist, curveOf, edgePaths, nearestWithin, stateR, turnPage, type BEdge, type Body, type Curve, type GNode, type Hop, type Planet, type Pt, type Scene, type Pager, type Star,
} from "./scene";
import { SIM_PERIOD } from "./mockSky";
import { Moves, PULSE, TRAVEL, hosted, merge, stateCount, withLedgers, type Move, type Sky } from "./sky";
import { branchLines, drawBranches, placeBranches, textHits } from "./transit";
import type { KanbanTask } from "../features/kanban/kanbanModel";
import { foldRows, openStream, type Link } from "../api/stream";
import { openLedger, type LedgerHead } from "../api/ledgerStream";
import { pushSchedulerStatus } from "../features/scheduler/scheduler";
import { UPDATING, linkHud } from "./connection";
import { keep as reuse } from "../api/same";
import { createHistory } from "../api/history";
import { sizes } from "./grow";
import { hostRun, laneRun, machineRun, subjectOf, traceCard, traceTable, type Run, type Subject } from "../features/level/trace";
import { boardTies, hangarLevel, tieLedger, type Ties } from "./dagTies";
import { pivotTip, tieTip } from "./dagTieTips";
import type { Dag, Delta, LedgerRow, Machine, RawTask, Snapshot, Writer } from "../api";
import { fanTip, stepStatus } from "../features/fanout/fanoutModel";
import { esc, fanList, queueCell, startRun, taskLink, taskPanel } from "./panels";
import { emptyFan, fanRows, queueRow, stepRuns, track, type Fan } from "../features/fanout/fan";
import { ADMIN_DEFAULTS, type AdminPrefs } from "../features/admin/adminPrefs";
import { clockHm, stamp } from "../shared/clock";
import { sizes as ledgerSizes } from "../features/level/machineLedger";
import { firstOpened, rowMeta } from "../features/level/machineRows";
import { asked, arrived as pageArrived, failed, nextQuery, paging, reveal, RETRY, wantNext, type Paging } from "../features/level/machinePaging";
import { dragTo, inputGoal, revealGoal, type ScrollInput } from "../features/level/machineScroll";
import { tickAt } from "../features/level/machineStrip";
import { heldBy, sessionsOf, traceSteps } from "../features/level/machineTrace";
import { backStep, canvasSpace, levelParams, levelSearch, replaceSearch, retired, viewOf, viewSearch } from "../shared/nav";
import { boardDraw } from "./boardDraw";
import { loadFold, loadMachineLedger, prefetchBoardExtras, type FoldDrawing, type MachineLedgerDrawing } from "./lazyBoardExtras";
import { LEDGER_PALETTE } from "./ledgerPalette";
import type { Rail } from "./machineLedgerDraw";
import { staged } from "./staged";
import { whenShown } from "./shown";
import { fitLevel, refitView, toScreen, wheelFactor, zoomAbout, zoomedIn, type View } from "./zoom";
import { loadFonts } from "./fonts";
import { feedOf, finished, heldTasks } from "./feed";
import { dagData, kanbanTasks, loadHudViews } from "./hudViews";
import type { Probe, Renderer } from "./rendererTypes";
import { keep, recall } from "./stored";
import { traceDraw } from "./traceDraw";

// the seeded night sky and its twinkle, the same as the current board's backdrop
let seed = 7;
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const STARS = Array.from({ length: 160 }, () => ({ x: rnd(), y: rnd(), r: rnd() * 1.1 + 0.2, p: rnd() * TAU }));



/** `onDrawn` runs once, in the frame whose canvas first shows the level (the page's first paint). */
export function renderer(cv: HTMLCanvasElement, hud: HudStore, els: { tip: HTMLElement; panel: HTMLElement }, demo: boolean, prefs: () => AdminPrefs = () => ADMIN_DEFAULTS, onDrawn?: () => void): Renderer {
  const cx = cv.getContext("2d")!, { tip, panel } = els;
  const hhmm = (sec: number) => clockHm(sec, prefs().clock);
  let S: Sky | null = null, snap: Snapshot | null = null, scene: Scene | null = null;
  /** Each DAG's runs as the panel last saw them, so a run that ends keeps its row for a moment. */
  const fans: Record<string, Fan> = {};
  const moves = new Moves();
  /** The feed's lines for the runs of every DAG that start, queue, change step or end. */
  const runEvents = new RunEvents();
  let path: Path = BOARD, W = 0, H = 0, view: View = { k: 1, x: 0, y: 0 }, fit: View = view;
  // the task whose path a click pinned, kept by id so each frame finds it again in the rebuilt scene
  let pin: Subject | null = null;
  // the Ledger merge whose panel is open, by key, so each frame and snapshot finds its row again
  let mergeSel: string | null = null;
  // the machine ledger's pinned task, by machine and session id, found again each frame in the newest snapshot
  /** The pinned ledger task: where it was clicked, its task and name, and the machines it had a session in then, which the card lists. */
  let lpin: { flow: string; id: string; task: string | null; label: string; machines: string[] } | null = null;
  /** The ledger row picked out on the top machine's level (its tie stays drawn), and the row that glows after stepping back out onto it. */
  let pickedRow: string | null = null, glow: { name: string; t0: number } | null = null;
  const pages: Record<string, number> = {};
  // the machine ledger's loaded pages, and the rows' scroll (the goal the input sets and the position drawn, eased to it)
  let pg: Paging | null = null, scrollGoal = 0, scrollPos = 0, thumbDrag: { y: number; g0: number } | null = null;
  // what a navigator search result under the pointer stands for, lit while the pointer is off the canvas
  let spotted: Target | null = null, spotNear = false;
  let hover: Hover | null = null, mouse: { ox: number; oy: number; cx: number; cy: number } | null = null;
  let trans: { snap: HTMLCanvasElement; inward: boolean; f: Pt; t0: number } | null = null, anim: ((now: number) => void) | null = null;
  let drag: { fixed: boolean; x: number; y: number; vx: number; vy: number; moved: boolean } | null = null;
  // ZS: zoom beyond the fit size; K: absolute zoom. Text, pulses and dashes divide by these so they never balloon.
  const grown = sizes(), bends = new Map<string, Pt>(); // each bent Board path's last bend, so it keeps its route while that clears
  let T = Date.now() / 1000, clock = 0, liveTasks = new Set<string>(), hotEdge = new Set<string>(), ZS = 1, K = 1;
  let away = false, timer = 0, fanTimer = 0, stopped = false, saveT = 0, tick = 0;
  // a delta behind another view skips the Star Map layout nothing draws, and lays it out when the map is shown or asked for
  const relay = whenShown(() => layout(true)), publishLater = staged();
  // The stream the page reads its snapshot and every change after it from.
  let stream: { close(): void } | null = null, last = 0;
  // The open Ledger's rows and the stream that feeds them: the snapshot carries none, so they are held here and put back into every sky `merge` builds.
  let ledgerRows: Sky["ledgers"] = {}, ledgerOpen: { event: string; stream: { close(): void } } | null = null;
  /** The clock time of the last data drawn, a note's "as of"; whether a newer page build is waiting for the page to be idle; and the wait's cancel. */
  let lastAt: string | null = null, updating = false, cancelReload: (() => void) | null = null;

  // The frame's drawing: the primitives read the zoom, clock, type scale and hover as they run, and the machine ledger draws from the state below.
  const dc: DrawCtx = {
    cx, get K() { return K; }, get ZS() { return ZS; }, get clock() { return clock; }, get scale() { return prefs().scale * (scene?.labelScale ?? 1); }, get hover() { return hover; },
  };
  const pen = drawing(dc);
  const { nameWidth, labPx } = pen;
  let mled: MachineLedgerDrawing | null = null;
  let foldDrawing: FoldDrawing | null = null;
  let extrasCancel: (() => void) | null = null;
  let ensureFold: () => FoldDrawing | null = () => null;
  const ensurePanel = () => { void loadLedgerPanel().then(() => loop.wake()); return ledgerPanel; };
  const mledIO = {
    get S() { return S; }, get scene() { return scene; }, get FW() { return FW; }, get H() { return H; }, get T() { return T; }, get hotEdge() { return hotEdge; },
    events: () => EVENTS(), hhmm, get scrollPos() { return scrollPos; }, get pg() { return pg; }, get pickedRow() { return pickedRow; }, get lpin() { return lpin; },
    get railHover() { return railHover; }, get thumbDrag() { return !!thumbDrag; }, get glow() { return glow; }, set glow(g) { glow = g; },
  };
  const ensureMled = (): MachineLedgerDrawing | null => {
    if (mled) return mled;
    void loadMachineLedger().then((mod) => {
      if (!mled) mled = mod.machineLedger(dc, pen, mledIO);
      loop.wake();
    });
    return null;
  };

  // A self-contained demo page: its embedded snapshot already holds every flow, and its address is not the server's.
  const fixture = embedded() !== null;
  // `?demo` and the embedded fixture load the walk helpers on demand; a served page never parses that tree for first paint.
  let demoWalk: { live: (prev: Snapshot, next: Snapshot) => Snapshot; step: (prev: Snapshot) => Snapshot } | null = null;
  if (demo || fixture) {
    void import("../demo/demo").then((m) => {
      demoWalk = { live: m.demoLive, step: m.demoStep };
    });
  }
  const level = (): Level => path[path.length - 1];
  const stateName = (id: string) => S?.board.machine.states.find((s) => s.id === id)?.name || id;
  const EVENTS = () => moves.events;
  const moving = (flow: string) => EVENTS().filter((e) => e.machine === flow && e.from && e.at <= T && T - e.at < TRAVEL);
  const cueLine = (n: string) => (S?.cues ?? []).filter((c) => c.dag === n).map((c) => `runs on ${esc(c.on)}, beside ${esc(c.event)}`).join("; ");
  const writes = (n: string) => Object.entries(S!.writers).filter(([, ws]) => ws.some((w) => w.actor === n)).map(([ev]) => ev);

  // ---- view: scroll zooms about the cursor (scale only, never changes level), drag pans; kept per screen size and level ----
  const railW = () => document.getElementById("rail")?.offsetWidth ?? 0;
  const navW = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--nav")) || 0;
  // the canvas is the page between the navigator and the rail, so its size (not the window's) keys the remembered zoom
  const viewKey = () => `fv.view.${W}x${H}.${pathKey(path)}.${scene?.w}x${scene?.h}`;
  // the default view fits the level's content box (the whole sky on the Board), centred between the open navigator and the
  // rail; a panel floats over it
  const fitScene = (): View => fitLevel(scene!, FW, H);
  const chromeBoxes = () => {
    const box = (el: Element | null) => {
      const b = el?.getBoundingClientRect();
      return b?.width ? [{ x0: b.left - L - 6, y0: b.top - 4, x1: b.right - L + 6, y1: b.bottom + 4 }] : [];
    };
    const crumb = box(document.getElementById("crumb"));
    return { avoid: crumb, inset: crumb[0] ? crumb[0].y1 + 2 : 0 };
  };
  /** Lay the level out for the canvas's shape, so a wider screen spreads it instead of framing it with empty sky. */
  function layout(keepView: boolean) {
    if (!S || !W) return;
    const was = fit;
    laidScale = prefs().scale;
    const mp = S.machinePage;
    if (mp?.open && pg?.top !== mp.open) pg = paging(mp, (n) => S!.flows[n]?.last ?? 0); // the snapshot names the first page; the pages loaded after it are kept across snapshots
    const held = scene?.top && (overRows() || lpin || pickedRow) ? scene.top.rows.map((r) => r.name) : undefined; // the pointer over the rows, a pinned path or a focused row holds their order
    // a pinned task narrows the rows to the machines it has a session in
    const only = lpin ? { task: lpin.label, machines: heldBy(S.flows, lpin.task, lpin.machines) } : undefined;
    scene = build({ S, moves, W: FW, H, T, host: hostOf(path), pages, ease: sized, routes: bends, scale: laidScale, measure: nameWidth, chrome: chromeBoxes(), held, paging: pg, only }, level());
    watchLedger(scene.fold?.ledger?.rows === "merge" ? scene.fold.ledger.event : null);
    if (scene.top) {
      scrollGoal = Math.min(scrollGoal, scene.top.max);
      scrollPos = Math.min(scrollPos, scene.top.max);
    }
    // the machine across a level's top is laid out in screen pixels: it is drawn at 1:1 from the fit box's left edge and never zooms or pans
    fit = scene.top ? { k: 1, x: 0, y: 0 } : fitScene();
    if (scene.pivot) edgePaths(scene, { k: fit.k, x: fit.x }, FW, stateName);
    if (scene.top) view = fit;
    else if (keepView) view = refitView(view, was, fit); // a view at the old fit follows the new one, so the sky zooms out smoothly as a state grows
    else {
      const kept = recall<View>(viewKey());
      view = kept && kept.k > fit.k * 1.02 ? kept : fit; // a remembered zoom-in survives a reload; anything at or below the fit re-centres
    }
  }
  /** Turn one state's machine page without moving the operator's current view. */
  function changePage(pager: Pager) {
    const kept = view;
    pages[pager.sid] = turnPage(pager);
    layout(true);
    view = kept;
    hover = null;
    tip.style.opacity = "0";
    loop.wake();
  }
  // the canvas's left edge on the page (the navigator's width) and the width the level is fitted in
  let L = 0, FW = 0, laidScale = 100;
  const resize = (keepView = false) => {
    const dpr = devicePixelRatio || 1;
    ({ left: L, width: W } = canvasSpace(innerWidth, navW(), railW()));
    FW = W;
    // the view bar along the bottom edge at phone width is not canvas
    H = innerHeight - (document.getElementById("pnav")?.offsetHeight ?? 0);
    cv.width = W * dpr;
    cv.height = H * dpr;
    cv.style.left = `${L}px`;
    cv.style.width = `${W}px`;
    cv.style.height = `${H}px`;
    layout(keepView);
  };
  const onResize = () => resize();
  const save = () => {
    clearTimeout(saveT);
    saveT = window.setTimeout(() => keep(viewKey(), view), 250);
  };
  function flyTo(target: View) {
    const from = { ...view }, t0 = performance.now();
    loop.wake();
    anim = (now) => {
      const e = ease(Math.min(1, (now - t0) / 450));
      view = { k: from.k + (target.k - from.k) * e, x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e };
      if (e >= 1) {
        anim = null;
        save();
      }
    };
  }

  // go to another level: the old level zooms through the clicked point (in) or shrinks away (out)
  function go(next: Path, fx = W / 2, fy = H / 2, then?: () => View) {
    const shot = document.createElement("canvas");
    shot.width = cv.width;
    shot.height = cv.height;
    shot.getContext("2d")!.drawImage(cv, 0, 0);
    const inward = next.length >= path.length, came = next.length === path.length - 1 ? path[path.length - 1] : null;
    path = next;
    keep("fv.path", path);
    pin = null;
    lpin = null;
    pickedRow = glow = null;
    mergeSel = null;
    panel.classList.remove("open");
    setHover(null);
    anim = null;
    pg = null; // a level's machine ledger opens at its first page, newest first
    scrollGoal = scrollPos = 0;
    layout(false);
    if (then) view = then();
    // stepping out of a machine zooms back down onto the row it came from, which glows a moment
    const top = scene?.top, row = came?.kind === "machine" ? top?.rows.find((r) => r.name === came.flow) : undefined;
    if (top && row) {
      glow = { name: row.name, t0: performance.now() };
      fx = top.metaX + top.metaW / 2;
      fy = Math.min(top.laneBottom, Math.max(top.laneTop, top.laneTop + row.y + row.h / 2));
    }
    syncUrl();
    hud.set({ path });
    trans = { snap: shot, inward, f: { x: fx, y: fy }, t0: performance.now() };
    loop.wake();
  }
  const zoomedOut = () => view.k <= fit.k * 1.02;
  const push = (l: Level, fx: number, fy: number) => go([...path, l], fx, fy);
  /** The address that reproduces this level: the machine on top when it is not the state's own, and the row picked out on it. */
  function syncUrl() {
    if (fixture || !S) return;
    const open = path[path.length - 1].kind === "machine" ? topFlow(S.tree.subs, path) : null;
    replaceSearch(location, levelSearch(location.search, { open, focus: pickedRow }), (url) => history.replaceState(null, "", url));
  }
  const setFocus = (name: string | null) => {
    pickedRow = name;
    syncUrl();
    loop.wake();
  };
  // step out one thing at a time: the open panel, the picked row, any zoom, then up a level (a machine, then the Board)
  const back = (fx?: number, fy?: number) => {
    const step = backStep({ panel: panel.classList.contains("open"), focus: pickedRow, scrolled: scene?.top ? scrollGoal > 0 : !zoomedOut(), depth: path.length });
    if (step === "panel") closePanel();
    else if (step === "focus") setFocus(null);
    else if (step === "scroll" && scene?.top) scrollGoal = 0;
    else if (step === "scroll") flyTo(fit);
    else if (step === "up") go(path.slice(0, -1), fx, fy);
  };
  /** A ledger row opens its machine on top, zooming through the point it was clicked. */
  const drill = (name: string, fx: number, fy: number) => {
    const to = S && pathTo(S.tree, name, hostOf(path));
    if (to) go(to, fx, fy);
  };

  const worldAt = (ox: number, oy: number) => ({ x: (ox - view.x) / view.k, y: (oy - view.y) / view.k });
  const inBox = (b: Hits["thumb"], p: Pt) => !!b && p.x >= b.x0 && p.x <= b.x1 && p.y >= b.y0 && p.y <= b.y1;
  // a merge Ledger's rows scroll under the templates by wheel, key or thumb, and nothing zooms there
  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    if (trans || !scene) return;
    const fold = scene.fold ? ensureFold() : null, grid = fold?.ledgerPort();
    if (fold && grid) {
      fold.scroll = wheelScroll(fold.scroll, grid, e, view.k);
      return;
    }
    if (scene.top) {
      scrollBy({ wheel: e.deltaY, lines: e.deltaMode === 1 });
      return;
    }
    anim = null;
    view = zoomAbout(view, fit, { x: e.offsetX, y: e.offsetY }, wheelFactor(e.deltaY, e.deltaMode, H)) ?? fit;
    save();
  };
  // right-click steps out, as Escape does
  const onContext = (e: MouseEvent) => {
    e.preventDefault();
    back(e.offsetX, e.offsetY);
  };
  const onDown = (e: MouseEvent) => {
    if (e.button !== 0) return;
    const fold = scene?.fold ? ensureFold() : null;
    if (fold?.ledgerGrid() && inBox(fold.scrollHits.thumb, worldAt(e.offsetX, e.offsetY))) {
      fold.scroll = dragStart(fold.scroll, e.clientY);
      return;
    }
    if (scene?.top && !trans && railHit(e.offsetX - view.x, e.offsetY)?.kind === "thumb") {
      thumbDrag = { y: e.clientY, g0: scrollGoal };
      return;
    }
    drag = { fixed: zoomedOut(), x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
  };
  const onUp = (e: MouseEvent) => {
    if (thumbDrag) {
      thumbDrag = null;
      return;
    }
    const fold = foldDrawing;
    if (fold?.scroll.drag) fold.scroll = { ...fold.scroll, drag: null };
    else if (drag && !drag.moved && e.target === cv) {
      const grid = fold?.ledgerPort();
      if (fold && grid && inBox(fold.scrollHits.chip, worldAt(e.offsetX, e.offsetY))) fold.scroll = keyScroll(fold.scroll, grid, "Home") ?? fold.scroll;
      else click(e.offsetX, e.offsetY);
    }
    drag = null;
  };
  const onMove = (e: MouseEvent) => {
    const led = mled;
    if (thumbDrag && led?.thumb && scene?.top) {
      scrollGoal = scrollPos = dragTo(led.thumb, thumbDrag.g0, e.clientY - thumbDrag.y, scene.top.max);
      return;
    }
    const fold = foldDrawing;
    if (fold?.scroll.drag) {
      const grid = fold.ledgerPort();
      if (grid) fold.scroll = dragMove(fold.scroll, grid, e.clientY, view.k, labPx(24));
      return;
    }
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      if (drag.fixed) return; // fully zoomed out: nothing to pan
      view = { ...view, x: drag.vx + dx, y: drag.vy + dy };
      save();
      return;
    }
    // the canvas is fixed at a known left edge, so the client point less that edge is the canvas point; offsetX would force a layout on every move
    mouse = e.target === cv && !trans ? { ox: e.clientX - L, oy: e.clientY, cx: e.clientX, cy: e.clientY } : null;
    if (!mouse && !spotted) setHover(null); // the pointer moving along the Recent rail keeps the card of the line it spots
  };
  const onLeave = () => {
    mouse = null;
    if (!spotted) setHover(null);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.target instanceof HTMLInputElement) return void (e.key === "Escape" && closePanel());
    if (away) return;
    const fold = scene?.fold ? ensureFold() : null, grid = fold?.ledgerPort(), next = fold && grid && !e.ctrlKey && !e.metaKey && !e.altKey ? keyScroll(fold.scroll, grid, e.key) : null;
    if (next && fold) {
      e.preventDefault();
      fold.scroll = next;
      return;
    }
    if (scene?.top && !trans && scrollBy({ key: e.key })) return void e.preventDefault();
    if (e.key === "Escape" || e.key === "Backspace") back();
    if (e.key === "0" && scene) flyTo(fit);
  };
  /** A hidden tab stops animating, so it drops the stream; on return the stream's fresh snapshot places everyone at once, replaying nothing missed. */
  const onVisibility = () => {
    if (demo) return;
    if (document.hidden) {
      stream?.close();
      stream = null;
      moves.resync(Date.now() / 1000);
    } else stream ??= openStream(connection);
  };

  // ---- data: every machine's tasks and the runs instances' workflows, pushed by the stream ----
  /** Each connect's snapshot and every delta after it, drawn at once. */
  function onSnapshot(next: Snapshot, kind?: Delta["kind"]) {
    const first = !S;
    if (demo && snap && demoWalk) {
      snap = demoWalk.live(snap, next);
      return;
    }
    if (kind === "ledgers" && S) return void applyLedgers(next);
    apply(next);
    if (first && demo && !stopped) timer = window.setTimeout(demoTick, 1200);
    if (first && SIM && !stopped) simTick();
  }
  // Preview only: `&sim=1`, `&sim=2` or `&sim=3` re-reads the snapshot each time the mock's step clock ticks, so every simulated task takes its next step
  const SIM = ["1", "2", "3"].includes(new URLSearchParams(location.search).get("sim") ?? "");
  let simAt = -1;
  const simTick = () => {
    if (stopped) return;
    const n = Math.floor(Date.now() / 1000 / SIM_PERIOD);
    if (snap && n !== simAt) {
      simAt = n;
      apply(snap);
    }
    window.setTimeout(simTick, 250);
  };
  function onLive(on: boolean) {
    if (!on) moves.resync(Date.now() / 1000); // the reconnect's snapshot places what the drop missed, as a returning tab's does
  }
  /** The dot and its note follow what the stream says it is doing; a note keeps the time of the last data drawn, which the Board still shows. */
  function onLink(link: Link) {
    hud.set(linkHud(link, lastAt, updating));
  }
  /** The server runs a page build other than the one loaded: the dot says so and the page reloads once nobody is using it. */
  function onBuild(id: string) {
    updating = true;
    cancelReload?.();
    void import("../api/reload").then(({ reloadWhenIdle }) => {
      if (!stopped && updating) cancelReload = reloadWhenIdle(id);
    });
    hud.set({ note: UPDATING });
  }
  const connection = {
    snapshot: onSnapshot,
    live: onLive,
    link: onLink,
    build: onBuild,
    scheduler: pushSchedulerStatus,
  };
  const demoTick = () => {
    if (stopped || !snap || !demoWalk) return;
    apply(demoWalk.step(snap));
    timer = window.setTimeout(demoTick, 600 + Math.random() * 1200);
  };
  function apply(next: Snapshot) {
    const first = !S;
    snap = next;
    T = Date.now() / 1000;
    S = { ...merge(next), ledgers: ledgerRows };
    for (const d of S.dags) fans[d.name] = track(fans[d.name] ?? emptyFan(), d, T);
    moves.observe(S, T);
    if (first) runEvents.resync(); // the runs already in flight when the page opens are not announced as new
    runEvents.observe(S.dags, T);
    if (first) {
      // A retired per-graph address opens its level; the page's one address is the root.
      const at = levelParams(location.search);
      path = startPath(location.pathname, location.hash, recall<Path>("fv.path"), S.tree, at);
      if (!fixture && retired(location.pathname, location.hash)) history.replaceState(null, "", "/" + viewSearch(location.search, viewOf(location.search), prefs().view));
      keep("fv.path", path);
    }
    if (first) layout(false);
    else relay.request();
    if (first) {
      const named = levelParams(location.search).focus;
      pickedRow = named && scene?.top?.rows.some((r) => r.name === named) ? named : null; // the address restores the row picked out, if this level still has it
      syncUrl();
      // Away-first open (Kanban/DAGs) never paints the canvas, so HUD cards/dagData cannot wait on first paint.
      void loadHudViews().then(() => { if (!stopped) publish(); });
    }
    publish();
    paintFan();
    paintMerge();
    if (away) heartbeat(); // the canvas draws no frame behind another view, but the Recent feed beside it stays current
    else loop.wake();
  }
  /** Holds the rows of the one Ledger that is open and follows it: opening another closes the stream of the last and drops its rows, and the page shows a loading state until the first page arrives. */
  function watchLedger(event: string | null) {
    if (event === (ledgerOpen?.event ?? null) || (event && !S)) return;
    ledgerOpen?.stream.close();
    ledgerOpen = null;
    ledgerRows = {};
    if (S) S = { ...S, ledgers: ledgerRows };
    if (!event || stopped) return;
    const got = (rows: LedgerRow[]) => {
      if (ledgerOpen?.event !== event) return;
      ledgerRows = { [event]: rows };
      S = { ...S!, ledgers: ledgerRows };
      relay.request();
      paintMerge();
      if (away) heartbeat();
      else loop.wake();
    };
    ledgerOpen = {
      event,
      stream: openLedger(event, { head: (page: LedgerHead) => got(page.rows), rows: (changed) => got(foldRows(ledgerRows[event] ?? [], changed)) }),
    };
  }
  /** A Ledger delta changes the merge rows and strip alone, so the sky, the HUD, the moves and the fans stay as they were and only the layout and the merge panel redraw. */
  function applyLedgers(next: Snapshot) {
    snap = next;
    T = Date.now() / 1000;
    S = withLedgers(S!, next);
    relay.request();
    paintMerge();
    if (away) heartbeat();
    else loop.wake();
  }
  /** What the HUD shows, written once per snapshot in tasks after the event's own, the build in one and the write that redraws the page in the next. */
  function publish() {
    publishLater(() => {
      const next = compose();
      return () => write(next);
    });
  }
  /** A delta rarely changes what the HUD shows, so only changed fields reach React and an unchanged HUD does not re-render; a field that
   * changed keeps the reference of each part of it that did not (a card by its id), so the views draw what changed and not all they hold. */
  function write(next: Partial<HudState>) {
    const now = hud.get() as unknown as Record<string, unknown>;
    const changed = Object.fromEntries(Object.entries(next).map(([k, v]): [string, unknown] => [k, k === "cards" ? reuse(now.cards as KanbanTask[], v as KanbanTask[], (c) => c.id) : reuse(now[k], v)]).filter(([k, v]) => v !== now[k]));
    if (Object.keys(changed).length) hud.set(changed);
  }
  function compose(): Partial<HudState> {
    const sky = S!, board = sky.board;
    const at = stamp(sky.now, prefs().clock);
    lastAt = hhmm(sky.now);
    const next: Partial<HudState> = {
      path,
      tree: sky.tree,
      stats: sky.error ? `live · ${at} MST · ${sky.error}` : `live · ${at} MST`,
      states: board.machine.states.map((s) => ({ id: s.id, name: s.name, count: stateCount(sky, s.id) })),
      counts: Object.fromEntries(Object.values(sky.flows).map((f) => [f.name, f.agents.length])),
      hostCounts: Object.fromEntries(Object.entries(sky.tree.subs).flatMap(([state, flows]) => flows.map((f) => [`${state}/${f}`, hosted(sky, f, state).length]))),
      dags: sky.dags.map((d) => d.name),
      ...(dagData && kanbanTasks ? { dagData: dagData(sky), cards: kanbanTasks(sky) } : {}),
      pools: sky.pools,
      milestoneDone: sky.milestoneDone,
      names: Object.fromEntries(board.machine.states.map((s) => [s.id, s.name])),
      types: Object.fromEntries(board.machine.states.map((s) => [s.id, s.role ?? null])),
      roles: sky.roles,
      claims: sky.claims,
      boardUrl: sky.boardUrl,
      capabilities: sky.capabilities,
      hint: sky.hint,
    };
    return next;
  }
  /** Every quarter second: the feed and the navigator's moving machines, written only when they change. */
  function heartbeat() {
    if (!S) return;
    const feed: FeedLine[] = feedOf(EVENTS(), S.dags, runEvents.lines, T, heldTasks(S.board)).map((l) => ({ ...l, time: hhmm(l.at) })), mv = [...new Set(EVENTS().filter((e) => e.from && e.at <= T && T - e.at < TRAVEL).map((e) => e.machine))].sort();
    const now = hud.get();
    if (feed.map((f) => f.key + f.at + f.time).join() !== now.feed.map((f) => f.key + f.at + f.time).join()) hud.set({ feed });
    if (mv.join() !== now.moving.join()) hud.set({ moving: mv });
  }

  // ---- motion: every orbiting body is placed from the clock each frame ----
  function update(t: number) {
    const sc = scene!, board = level().kind === "board";
    for (const l of [...sc.hops, ...sc.entries, ...sc.exits]) l.busy = false; // a path glows while a task travels it
    hotEdge = new Set(EVENTS().filter((e) => e.from && e.at <= T && T - e.at < TRAVEL).map((e) => `${e.machine}:${e.from}>${e.to}`));
    for (const k of sc.tasks) {
      const a = k.a0 + k.w * t, R = k.R;
      k.ang = a;
      k.x = k.host.x + Math.cos(a) * R;
      k.y = k.host.y + Math.sin(a) * R;
      k.moving = false;
      k.arrive = null;
      k.gone = false;
      k.via = null;
      if (level().kind === "state" && !k.today && stateHop(k, t)) continue;
      // a task whose machine is changing its state leaves its orbit, rides the machine's chord like the current board's hop (ease-out, comet tail),
      // rings the state it lands on, then drops back into orbit
      const st = k.host.states, ev = st && EVENTS().findLast((e) => e.task === k.id && e.machine === k.host.name && e.from && st[e.from] && st[e.to] && e.from !== e.to && e.at <= T && T - e.at < TRAVEL + PULSE);
      if (!st || !ev) continue;
      const u = (T - ev.at) / TRAVEL;
      if (u >= 1) {
        k.arrive = { x: st[ev.to].x, y: st[ev.to].y, col: st[ev.to].color, age: (T - ev.at - TRAVEL) / PULSE };
        continue;
      }
      const c = curveOf(st[ev.from!], st[ev.to]), q = bez(c.p0, c.c, c.p1, easeO(u)), edge = Math.min(1, u / 0.12, (1 - u) / 0.05);
      k.x += (q.x - k.x) * edge;
      k.y += (q.y - k.y) * edge;
      k.moving = true;
      k.hop = { c, u: easeO(u) };
    }
    // the phase machines keep off every hangar's name and orbiters, drawn or not, so a DAG starting never moves a machine
    const orb = 7 / fit.k;
    if (board) sc.hangars = (ties()?.pivots ?? []).flatMap((h) => [{ of: `hangar:${h.state}`, x0: h.box[0], y0: h.box[1], x1: h.box[2], y1: h.box[3] }, ...h.orbs.map((o) => ({ of: `hangar:${o.dag}`, x0: o.x - orb, y0: o.y - orb, x1: o.x + orb, y1: o.y + orb }))]);
    gliding = board && placeBranches(sc, performance.now() / 1000);
    liveTasks = new Set(EVENTS().filter((e) => e.task && e.at <= T && T - e.at < TRAVEL).map((e) => e.task!));
  }
  /** A phase branch is still growing, retracting or gliding a dot, so the next frame is needed. */
  let gliding = false;

  // where an orbiting task was at page time tt
  const orbitAt = (k: Body, tt: number): Pt => {
    const a = k.a0 + k.w * tt, R = k.R;
    return { x: k.host.x + Math.cos(a) * R, y: k.host.y + Math.sin(a) * R };
  };
  function ride(k: Body, p0: Pt, p1: Pt, u: number, via: string) {
    const dx = p1.x - p0.x, dy = p1.y - p0.y, c = { x: (p0.x + p1.x) / 2 - dy * 0.12, y: (p0.y + p1.y) / 2 + dx * 0.12 }, e = easeO(u), q = bez(p0, c, p1, e);
    k.x = q.x;
    k.y = q.y;
    k.moving = true;
    k.hop = { c: { p0, c, p1 }, u: e };
    k.via = via;
  }
  // the Board's hop on a drawn path: ease-out along it with a comet tail, the path glowing while the task is on it
  function follow(k: Body, l: (BEdge | Hop) & Partial<Curve>, u: number, via: string) {
    const c = l as Curve, e = easeO(u), q = bez(c.p0, c.c, c.p1, e);
    k.x = q.x;
    k.y = q.y;
    k.moving = true;
    k.hop = { c: { p0: c.p0, c: c.c, p1: c.p1 }, u: e };
    k.via = via;
    l.busy = true;
  }
  // state level: a task is drawn only while it holds this Board state. A Board move out of it follows that transition's path off the right edge;
  // a move in follows its path in from the left edge; when its work opens a skill machine or returns from one, it follows the path between the
  // two machines. Each lands with the arrival rings, as on the Board. A task in a skill machine when its Board state changes has no path of its
  // own and rides straight to or from the edge. Returns true when it placed the task.
  function stateHop(k: Body, t: number): boolean {
    const sc = scene!;
    let bs: Move | null = null;
    for (const e of k.bev) if (e.at <= T) bs = e;
    const held = bs ? bs.to : k.bev.length ? k.bev[0].from : k.state, age = bs ? (T - bs.at) / TRAVEL : 9, back = (e: Move) => t - (T - e.at);
    const hostThen = (at: number) => !sc.hostAt || sc.hostAt(k.id, at) === k.host.name, pivot = sc.pivot!, onPivot = k.host === pivot;
    if (held !== sc.sid) {
      if (bs && bs.from === sc.sid && age < 1 && hostThen(bs.at)) {
        const to = bs.to, l = sc.exits.find((x) => x.target === to), via = `to ${stateName(to)}`;
        if (l && onPivot) follow(k, l, age, via);
        else ride(k, orbitAt(k, back(bs)), l?.p1 ?? { x: sc.w * 2, y: pivot.y }, age, via);
        return true;
      }
      k.gone = true;
      return true;
    }
    if (!hostThen(T)) {
      k.gone = true;
      return true;
    }
    const ring = (at: number) => {
      const q = (T - at - TRAVEL) / PULSE;
      if (q >= 0 && q < 1) k.arrive = { x: k.host.x, y: k.host.y, r: (k.host.R || k.host.r || 0) + 14, col: k.host.states ? "#c084fc" : (k.host.color ?? "#94a3b8"), age: q };
    };
    if (bs && bs.from !== sc.sid) {
      if (age < 1) {
        const from = bs.from, l = sc.entries.find((x) => x.source === from), via = `from ${stateName(from ?? "")}`;
        if (l && onPivot) follow(k, l, age, via);
        else ride(k, l?.p0 ?? { x: -sc.w, y: pivot.y }, { x: k.x, y: k.y }, age, via);
        return true;
      }
      ring(bs.at);
    }
    if (!sc.hostAt) return !!k.arrive;
    const he = EVENTS().findLast((e) => e.task === k.id && e.at <= T && e.machine === ((k.host as Planet).machine ?? k.host.name)), prev = he && sc.hostAt(k.id, he.at - 0.001);
    if (!he || prev === k.host.name || (bs && bs.at > he.at)) return !!k.arrive;
    const from = sc.tasks.find((q) => q.id === k.id && q.host.name === prev), u = (T - he.at) / TRAVEL, l = sc.hops.find((x) => x.from === prev && x.to === k.host.name);
    if (from && u < 1) {
      if (l) follow(k, l, u, `to ${k.host.name}`);
      else ride(k, orbitAt(from, back(he)), { x: k.x, y: k.y }, u, `to ${k.host.name}`);
      return true;
    }
    ring(he.at);
    return !!k.arrive;
  }

  // ---- hit testing (world units). Points keep a floor in screen px; lines get a 14 px band, wider than they draw ----
  const px = (n: number) => n / view.k;
  /** What the machine across a level's top is under (x, y): a task, a state or a flow line, each sized to grow with the text. */
  function hitTop(sc: Scene, x: number, y: number): Hover | null {
    const led = ensureMled();
    if (!led) return null;
    const { gs } = ledgerSizes(prefs().scale), top = sc.top!;
    for (const t of led.tasks) if (Math.hypot(t.x - x, t.y - y) < 11) return { kind: "ltask", o: t.o };
    if (y >= top.laneTop && y < top.laneBottom && x > top.metaX - 10 && x < top.x1 + 20) {
      const d = led.lane.find((q) => y >= q.y && y < q.y + q.row.h);
      if (!d) return null;
      const n = d.row.nodes.find((q) => Math.hypot(q.x - x, d.y + d.row.c + q.oy - y) < q.r + 4 * gs);
      return n ? { kind: "rstate", o: n } : { kind: "row", o: d.row };
    }
    for (const n of sc.top!.nodes) if (Math.hypot(n.x - x, n.y - y) < n.r + 4 * gs) return { kind: "state", o: sc.mStates[n.id] };
    const lines = sc.mEdges.filter((e) => e.a && e.b && e.a !== e.b).map((e) => ({ h: { kind: "medge", o: e } as Hover, d: curveDist(curveOf(e.a!, e.b!, e.bend), x, y) }));
    return nearestWithin(lines, (l) => l.d, 14)?.h ?? null;
  }
  function hit(x: number, y: number): Hover | null {
    const sc = scene!, near = (o: Pt, r: number) => Math.hypot(o.x - x, o.y - y) < r;
    if (sc.top) return hitTop(sc, x, y);
    const mine = scene?.fold ? (ensurePanel()?.ledgerHit(scene, doctor, x, y, px, ensureFold()?.ledgerShown() ?? []) ?? null) : null;
    if (mine) return mine;
    for (const s of sc.machineTasks) if (s._x !== undefined && Math.hypot(s._x - x, s._y! - y) < Math.max(4, px(7))) return { kind: "mtask", o: s };
    for (const t of sc.tasks) if (!t.gone && near(t, Math.max(t.big ? 7 : 5, px(7)))) return { kind: "task", o: t };
    // a wide DAG's circle overlaps its docked neighbours, so the nearest DAG in range wins, not the first
    let star: Star | null = null, sd = Infinity;
    for (const s of Object.values(sc.stars)) {
      const d = Math.hypot(s.x - x, s.y - y);
      if (d < Math.max(s.br, px(10)) && d < sd) [star, sd] = [s, d];
    }
    if (star) return { kind: "dag", o: star };
    // a tied DAG's orbiter, then its hangar's name block: the name is the hangar, which has no disc of its own
    const tz = ties();
    for (const h of tz?.pivots ?? []) for (const o of h.orbs) if (near(o, px(9))) return { kind: "tie", o };
    for (const h of tz?.pivots ?? []) if (x > h.box[0] && x < h.box[2] && y > h.box[1] && y < h.box[3]) return { kind: "pivot", o: h };
    for (const c of sc.fold?.ledger?.cols ?? []) if (x > c.x0 && x < c.x1 && y > c.y0 && y < c.y1) return { kind: "caption", o: c };
    for (const s of Object.values(sc.mStates)) if (near(s, Math.max(stateR(s), px(9)))) return { kind: "state", o: s };
    for (const p of sc.planets) if (near(p, p.subState ? Math.max(p.R, px(8)) : p.moon ? Math.max(p.R + 4, px(10)) : p.R + 16)) return { kind: "planet", o: p };
    if (sc.sun && near(sc.sun, sc.sun.r + 8)) return { kind: "sun", o: sc.sun };
    for (const b of sc.subStates) if (near(b, Math.max(b.R, px(8)))) return { kind: "sat", o: b };
    for (const m of sc.moons) if (near(m, Math.max(m.R + 4, px(10)))) return { kind: "moon", o: m };
    for (const g of Object.values(sc.galaxies)) if (near(g, g.edge)) return { kind: "galaxy", o: g };
    // nearest line within the band wins, so parallel edges pick the one under the cursor
    const lines: { h: Hover; d: number }[] = [];
    for (const e of sc.mEdges) if (e.a && e.b && e.a !== e.b) lines.push({ h: { kind: "medge", o: e }, d: curveDist(curveOf(e.a, e.b), x, y) });
    for (const e of [...sc.bEdges, ...sc.entries, ...sc.exits])
      if (e.p0) lines.push({ h: { kind: "bedge", o: e }, d: curveDist(e as Curve, x, y) });
    for (const e of sc.hops) lines.push({ h: { kind: "link", o: e }, d: curveDist(e, x, y) });
    return nearestWithin(lines, (l) => l.d, px(14))?.h ?? null;
  }
  let tipSize = { width: 0, height: 0 };
  /** Rewrites the tip's text and measures it, so placement uses the size of what is shown. */
  function retip(h: Hover) {
    tip.innerHTML = tipHtml(h);
    tipSize = tip.getBoundingClientRect();
  }
  function setHover(h: Hover | null, mx = 0, my = 0) {
    const same = h && hover && h.kind === hover.kind && h.o === hover.o;
    hover = h;
    if (!h) {
      tip.style.opacity = "0";
      return;
    }
    // measured only when the text changes: reading it every frame after moving the tip forces a layout per frame
    if (!same) retip(h);
    const r = tipSize;
    let tx = mx + 16, ty = my + 14;
    if (tx + r.width > innerWidth - railW() - 8) tx = mx - r.width - 16;
    if (ty + r.height > innerHeight - 8) ty = my - r.height - 14;
    tip.style.left = `${tx}px`;
    tip.style.top = `${ty}px`;
    tip.style.opacity = "1";
  }
  // ---- the back-trace: the path a hovered or pinned task took through this level's machine ----
  const pinnable = (s: Subject) => !scene?.top && (s.kind === "task" ? level().kind === "board" || level().kind === "state" : level().kind === "machine");
  const goalOf = (m?: Machine) => m?.states.find((x) => x.final)?.name ?? "its end";
  /** A task's run, or why there is none yet. */
  function runFor(s: Subject): Run | "loading" | "unavailable" {
    if (s.kind === "task" && level().kind === "state") {
      const flow = scene!.pivot?.name, rows = flow ? hist.machine(s.id, flow) : "unavailable";
      // the lane change that brought it here starts the run, so a task with no moves on this level still holds the body it orbits
      const lane = hist.lane(s.id), last = typeof lane === "string" ? undefined : lane.at(-1);
      const host = scene!.tasks.find((t) => t.id === s.id && !t.gone)?.host;
      const entry = last && host ? { at: last.at, from: last.from ?? "new", to: host.name } : undefined;
      return typeof rows === "string" ? rows : hostRun(scene!.hostTrail!(s.id), T, { flow: flow!, path: rows.path }, entry);
    }
    if (s.kind === "task") {
      const rows = hist.lane(s.id);
      return typeof rows === "string" ? rows : laneRun(rows, S!.board.machine, T);
    }
    const rows = hist.machine(s.id, s.flow), m = S!.flows[s.flow]?.machine;
    return typeof rows === "string" ? rows : m ? machineRun(rows.path, m, rows.steps, T) : "unavailable";
  }
  const hist = createHistory({
    onChange: () => {
      if (hover) retip(hover);
      paintTable();
      loop.wake();
    },
  });
  // ---- the Ledger: its rows' tips and panel, the doctor's banner, and the merge in focus ----
  const contract = createContract({ onChange: () => loop.wake() });
  const rerunStore = new RerunStore(undefined, () => [paintMerge(), loop.wake()]);
  /** Where the banner was drawn this frame, and the report it states; none off a merge Ledger or before a report. */
  let doctor: DoctorBox | null = null;
  const heldRows = () => {
    const led = scene?.fold?.ledger, held = led ? S?.ledgers[led.event] ?? [] : [];
    const fold = foldDrawing, rows = held.length && fold && held === fold.scrollHeld ? fold.scroll.rows : held, extra = S?.mergePins ?? [];
    if (!extra.length) return rows;
    const have = new Set(rows.map((r) => r.key)), more = extra.filter((r) => !have.has(r.key));
    return more.length ? [...rows, ...more] : rows;
  };
  function panelCtx(): PanelCtx {
    const sc = scene!, fold = sc.fold!, led = fold.ledger!, rows = heldRows(), byKey = new Map(rows.map((r) => [r.key, r])), dags = led.cols.map((c) => c.dag);
    return {
      event: led.event, from: fold.a!.name, to: fold.b!.name, ties: led.cols,
      steps: Object.fromEntries(dags.map((d) => [d, sc.stars[d].glyph.nodes.map((n) => n.name)])),
      optional: Object.fromEntries(dags.map((d) => [d, optionalSteps(rows, d)])), runnable: S!.runnable,
      palette: LEDGER_PALETTE, now: T, hm: hhmm, by: (k) => byKey.get(k), task: (id) => taskLink(id, id, S!), rerun: rerunStore.state,
    };
  }
  /** The row whose panel is open, if one is. */
  const openRow = () => (mergeSel && panel.classList.contains("open") ? heldRows().find((r) => r.key === mergeSel) ?? null : null);
  /** The merge the Ledger's templates are coloured by: the hovered row, else the open one, else the newest. */
  const focused = () => ensurePanel()?.focusRow(hover?.kind === "lrow" ? hover.o : null, openRow(), heldRows());
  const starOfStep = (n: GNode) => Object.values(scene!.stars).find((s) => s.glyph.nodes.includes(n));
  /** The merge panel's force-rerun buttons post to the rerun route; the store repaints the panel with the run's refusal. */
  const wireRerun = () => panel.querySelectorAll<HTMLElement>("[data-rerun]").forEach((b) => void (b.onclick = () => void rerunStore.run(b.dataset.rerun!, T)));
  function openMerge(row: LedgerRow) {
    panel.innerHTML = ensurePanel()?.mergePanel(row, panelCtx()) ?? "";
    wireRerun();
    openPanel();
    mergeSel = row.key;
  }
  /** Repaint the open merge's panel from its row as the snapshot now has it. */
  function paintMerge() {
    const row = openRow();
    if (!row || !scene?.fold?.ledger) return;
    const top = panel.scrollTop;
    panel.innerHTML = ensurePanel()?.mergePanel(row, panelCtx()) ?? "";
    panel.querySelector<HTMLElement>(".x")!.onclick = () => closePanel();
    wireRerun();
    panel.scrollTop = top;
  }
  const SLOT = '<div id="trace-slot"></div>';
  /** The pinned panel's hop table, once the history has it. */
  function paintTable() {
    const slot = panel.querySelector<HTMLElement>("#trace-slot");
    if (!slot || !pin || !S) return;
    const run = runFor(pin);
    slot.innerHTML = typeof run === "string" ? `<div class="k" style="margin-top:12px">${run === "loading" ? "tracing its path…" : "history unavailable"}</div>` : traceTable(run, level().kind === "state" ? planetName : pin.kind === "task" ? stateName : (id) => id, prefs().clock);
  }
  const writerLine = (w: Writer & { event?: string }) => `${esc(w.actor)} <span class="k">${w.event ? `writes ${esc(w.event)} ` : ""}via ${esc(w.trigger)}</span>`;
  const pagerTip = (pager: Pager) =>
    `<div class="k">page ${pager.page + 1} of ${pager.pages} · click to turn ${pager.d < 0 ? "back" : "forward"} to page ${turnPage(pager) + 1}</div><div class="n">${esc(pager.title)}</div>${pager.hidden.length ? `${pager.hidden.length} lifecycle machine${pager.hidden.length === 1 ? "" : "s"} this way<br>${pager.hidden.slice(0, 12).map(esc).join("<br>")}${pager.hidden.length > 12 ? "<br>…" : ""}` : ""}`;
  function tipHtml(h: Hover): string {
    const sky = S!;
    switch (h.kind) {
      case "task": {
        const o = h.o, at = subjectOf(h)!, kind = `task · ${stateName(o.state)}${o.today ? " today" : ""}${o.host.states ? ` · orbiting ${(o.host as Planet).title || o.host.name}` : ""} · click ${pinnable(at) ? "to pin its path" : "for details"}`;
        return traceCard({ kind, id: o.id, title: o.title, goal: goalOf(sky.board.machine) }, runFor(at), prefs().clock);
      }
      case "mtask": {
        const o = h.o, at = subjectOf(h)!, kind = `${taskKicker(o.machine, o._state || o.state, sourceOf(o.machine))} · click ${pinnable(at) ? "to pin its path" : "for details"}`;
        return traceCard({ kind, id: o.id, title: "", goal: goalOf(sky.flows[o.machine]?.machine) }, runFor(at), prefs().clock);
      }
      case "dag": {
        const o = h.o, crit = (o.tether?.crit ?? []).map(esc).join("<br>"), l = sky.launches.filter((x) => x.dag === o.name && x.machine).map((x) => x.machine!);
        return `<div class="k">DAG · ${esc(o.group)} · ${esc(o.active?.some((r) => r.status === "running") ? "running" : o.status)}${o.runnable ? " · runnable" : ""}</div><div class="n">${esc(o.name)}</div>${fanTip(o, S?.pools)}${crit ? `<div class="k">${crit}</div>` : ""}${l.length ? `<div class="k">launches ${l.map(esc).join(", ")}</div>` : ""}${o.steps.length} step${o.steps.length === 1 ? "" : "s"}: ${o.steps.map((s) => esc(s.name)).join(" → ")}${o.finishedAt ? `<div class="k">last run ${hhmm(finished(o.finishedAt))} MST</div>` : ""}`;
      }
      case "galaxy":
        return `<div class="k">Board state · click to open</div><div class="n">${esc(h.o.name)}</div>${h.o.n} tasks${h.o.today === undefined ? "" : ` · ${h.o.today} today`}${h.o.subs.length ? ` · ${h.o.subs.length} lifecycle machines inside` : ""}`;
      case "moon": {
        const o = h.o, mv = moving(o.name).length, nAgents = hosted(sky, o.name, o.parent.id).length;
        if (o.pager) return pagerTip(o.pager);
        return `<div class="k">${sourceOf(o.name) ? `machine mapped from ${esc(sourceOf(o.name)!)}` : "lifecycle machine"} inside ${esc(o.parent.name)} · click to open it</div><div class="n">${esc(o.name)}</div>${o.nStates} states · ${nAgents} session${nAgents === 1 ? "" : "s"}${mv ? ` · ${mv} moving now` : ""}`;
      }
      case "sat":
        return `<div class="k">state of the ${esc(h.o.machine)} machine · opens ${esc(h.o.machine)} ${esc(h.o.when)} · click to open ${esc(h.o.machine)}</div><div class="n">${esc(h.o.name)}</div>${h.o.n} task${h.o.n === 1 ? "" : "s"} orbiting`;
      case "sun":
        return `<div class="k">Board state</div><div class="n">${esc(h.o.name)}</div>${h.o.n} tasks${h.o.today === undefined ? "" : ` · ${h.o.today} today`}${scene!.planets.length ? ` · ${scene!.planets.length} lifecycle machines orbiting it` : ""}`;
      case "state":
        return `<div class="k">${esc(h.o.machine)} state</div><div class="n">${esc(h.o.name)}</div>${h.o.n} task${h.o.n === 1 ? "" : "s"} here now${h.o.loops.length ? `<div class="k">stays here on ${h.o.loops.map(esc).join(", ")}</div>` : ""}`;
      case "planet": {
        const o = h.o, mv = moving(o.name).length;
        if (o.pager) return pagerTip(o.pager);
        if (o.subState) return `<div class="k">state of the ${esc(o.machine!)} machine · opens ${esc(o.flow!)} ${esc(o.when ?? "")} · click to open it</div><div class="n">${esc(o.title!)}</div>${o.n} task${o.n === 1 ? "" : "s"} here now`;
        return `<div class="k">${sourceOf(o.name) ? `machine mapped from ${esc(sourceOf(o.name)!)}` : "lifecycle machine"} · click to open${o.when ? ` · ${esc(o.when)}` : ""}</div><div class="n">${esc(o.name)}</div>${Object.keys(o.states).length} states · ${o.n} task${o.n === 1 ? "" : "s"}${mv ? ` · ${mv} moving now` : ""}`;
      }
      case "caption": {
        const o = h.o, ev = sky.board.machine.transitions.find((t) => t.event === scene!.fold?.ledger?.event);
        const yaml = o.role === "writer" ? [`writes: ${scene!.fold!.ledger!.event}`, `trigger: ${o.on}`] : [`cue:`, `  event: ${scene!.fold!.ledger!.event}`, `  state: ${ev?.target ?? ""}`, `  on: ${o.on}`, ...(o.resolves ? [`  resolves: ${o.resolves}`] : [])];
        return `<div class="k">declared contract · click for the DAG</div><div class="n">${esc(o.dag)}: ${o.role === "writer" ? "writes" : "cued by"} ${esc(scene!.fold!.ledger!.event)}</div><pre>${yaml.map(esc).join("\n")}</pre>${o.resolves ? `<div class="k">a failed run clears ${o.resolves === "forced" ? "only on a green forced rerun" : "on the DAG's next green run"}</div>` : ""}`;
      }
      case "lrow":
        return ensurePanel()?.mergeTip(h.o, panelCtx()) ?? "";
      case "lstep": {
        const star = starOfStep(h.o), p = ensurePanel();
        return star && p ? p.stepTip(star.name, h.o.name, star.steps.find((st) => st.name === h.o.name)?.depends ?? [], focused(), panelCtx()) : "";
      }
      case "ljunction":
        return ensurePanel()?.junctionTip(heldRows(), panelCtx()) ?? "";
      case "ldoctor":
        return ensurePanel()?.doctorTip(h.o) ?? "";
      case "link":
        return `<div class="k">machine path · ${esc(h.o.from)} → ${esc(h.o.to)}</div><div class="n">${h.o.back ? "the task returns from the skill" : "a task opens this skill"}</div>`;
      case "ltask": {
        const { flow, agent } = h.o, oth = sessionsOf(sky.flows, flow, agent).filter((b) => b.agent.id !== agent.id || b.machine !== flow);
        return `<b>${esc(agent.task || agent.title)}</b> <span class="k">${esc(boardTitle(agent))}</span><br>${esc(stName(flow, agent.state))} <span class="k">on ${esc(flow)} · ${hhmm(agent.active ?? 0)}</span>` +
          (oth.length ? `<br><span class="k">also on</span> ${oth.map((b) => `${esc(b.machine)} › ${esc(stName(b.machine, b.agent.state))}`).join(", ")}` : "") + `<div class="k">its path is traced in order · click to pin it</div>`;
      }
      case "row": {
        const m = rowMeta(sky.flows, h.o.name, scene!.top!.machine, T);
        return `<div class="k">${esc(m.tie.text)}</div><div class="n">${esc(h.o.name)}</div>${esc(m.sub)}<div class="k">${esc(m.status.text)}</div>`;
      }
      case "rstate": {
        const o = h.o, row = scene!.top!.rows.find((r) => r.nodes.includes(o))!;
        return `<div class="k">${esc(row.name)} state</div><div class="n">${esc(o.name)}</div>${o.n} task${o.n === 1 ? "" : "s"} here now`;
      }
      case "medge":
        return `<div class="k">${esc(h.o.machine)} transition · ${esc(h.o.source)} → ${esc(h.o.target)}</div><div class="n">${esc(h.o.event)}</div>`;
      case "pivot":
        return pivotTip(h.o, { sky, stateName });
      case "tie":
        return tieTip(h.o, { sky, stateName, ev: tieLedger(boardSource(), h.o)?.ev ?? null, last: (d) => `last run ${hhmm(finished(d.finishedAt))} MST` });
      case "bedge":
        return `<div class="k">Board transition${h.o.events.length > 1 ? `s (${h.o.events.length})` : ""} · ${esc(h.o.source)} → ${esc(h.o.target)}${ledgerOfEdge(h.o) ? " · click for its Ledger" : ""}</div><div class="n">${h.o.events.map(esc).join("<br>")}</div>${h.o.writers.length ? h.o.writers.map(writerLine).join("<br>") : '<span class="k">no writer declared</span>'}`;
    }
  }

  // ---- click: drill into states, machines and DAGs, open panels for tasks ----
  // the panel floats over the level, so opening or closing it never moves or zooms the view
  const openPanel = () => {
    mergeSel = null;
    panel.classList.add("open");
    panel.querySelector<HTMLElement>(".x")!.onclick = () => closePanel();
  };
  /** Pin a ledger task, or release it: the rows narrow to the machines it has a session in, or widen back, and show from the top. */
  function pinLedger(to: typeof lpin) {
    if (lpin?.flow === to?.flow && lpin?.id === to?.id) return;
    lpin = to;
    if (!scene?.top) return;
    scrollGoal = scrollPos = 0;
    layout(true);
  }
  /** Close the panel if one is open; whether one was. */
  function closePanel() {
    pin = null;
    mergeSel = null;
    pinLedger(null);
    if (!panel.classList.contains("open")) return false;
    panel.classList.remove("open");
    return true;
  }
  /** The three parts of a DAG panel that follow its runs: the Queue row, the Steps chips and the In-flight list. */
  function fanParts(o: Dag, now: number) {
    const sky = S!, q = queueRow(o, snap?.pools ?? undefined), rows = fanRows(fans[o.name] ?? emptyFan(), o, now, sky.board.agents.map((a) => a.id));
    const last = `${esc(o.status)}${o.finishedAt ? ` ${hhmm(finished(o.finishedAt))} MST` : ""}`;
    return {
      queue: q ? queueCell(q) : "",
      steps: o.steps.map((s) => { const n = stepRuns(o, s.name); return `<span class="chip" style="color:${DAG_COLOR[stepStatus(o, s.name, s.status)] || "#94a3b8"}">${esc(s.name)}${n ? ` ×${n}` : ""}</span>${s.depends.length ? `<span class="k"> after ${s.depends.map(esc).join(", ")}</span>` : ""}`; }).join("<br>"),
      list: fanList(rows, last, (id) => taskLink(id, id, sky)),
    };
  }
  /** Repaint the open DAG panel's runs; its Run button and note stay as they are. */
  function paintFan() {
    const box = panel.classList.contains("open") ? panel.querySelector<HTMLElement>(".fan") : null, o = box && S?.dagBy[box.dataset.dag ?? ""];
    if (!box || !o) return;
    const parts = fanParts(o, Date.now() / 1000), row = panel.querySelector<HTMLElement>(".fan-q")!, top = panel.scrollTop;
    row.hidden = !parts.queue;
    row.querySelector("td:last-child")!.innerHTML = parts.queue;
    panel.querySelector(".fan-steps")!.innerHTML = parts.steps;
    box.innerHTML = parts.list;
    panel.scrollTop = top;
  }
  function openDagPanel(o: Dag & { group: string; runnable: boolean }) {
    const sky = S!, span = o.startedAt ? ` · ${hhmm(finished(o.startedAt))}–${o.finishedAt ? hhmm(finished(o.finishedAt)) : "…"} MST` : "", f = fanParts(o, Date.now() / 1000);
    panel.innerHTML = `<span class="x">✕</span><div class="k">DAG · ${esc(o.group)}</div><h2>${esc(o.name)}</h2>
      <table><tr class="fan-q"${f.queue ? "" : " hidden"}><td>Queue</td><td>${f.queue}</td></tr>
      <tr><td>Last run</td><td>${esc(o.status)}${o.raw ? ` (${esc(o.raw)})` : ""}${span}</td></tr>
      <tr><td>Steps</td><td class="fan-steps">${f.steps}</td></tr>
      <tr><td>Writes</td><td>${writes(o.name).map(esc).join(", ") || "no Board lane"}</td></tr>
      <tr><td>Launches</td><td>${sky.launches.filter((l) => l.dag === o.name).map((l) => esc(l.skill)).join(", ") || "no agent"}</td></tr>${cueLine(o.name) ? `
      <tr><td>Runs with</td><td>${cueLine(o.name)}</td></tr>` : ""}</table>
      ${o.active ? `<div class="fan" data-dag="${esc(o.name)}">${f.list}</div>` : ""}<button class="run" ${o.runnable ? "" : "disabled"}>▶ Run now</button>
      <div class="note">${o.runnable ? "Declared safe to re-run (idempotent)." : "Not declared idempotent, so the page offers no run control."}</div>`;
    const run = panel.querySelector<HTMLButtonElement>(".run")!, note = panel.querySelector<HTMLElement>(".note")!;
    // the run then appears through the event stream, like any other
    run.onclick = async () => {
      run.disabled = true;
      note.textContent = "Starting…";
      note.textContent = await startRun(o.name);
      run.disabled = false;
    };
    openPanel();
  }
  const boardSource = () => ({ flows: [S!.board], cues: S!.cues });
  const ledgerOfEdge = (e: BEdge) => (S ? pathLedger(boardSource(), e.events) : null);
  /** A state's name in one machine of the ledger. */
  const stName = (m: string, s: string) => S?.flows[m]?.machine.states.find((x) => x.id === s)?.name ?? s;
  const boardTitle = (a: RawTask) => S?.board.agents.find((b) => b.id === a.task)?.title ?? "";
  /** A click on a ledger task pins its path and lists its sessions and its steps in the panel. */
  function openLedgerTask(o: LTask) {
    const sky = S!, all = sessionsOf(sky.flows, o.flow, o.agent);
    pinLedger({ flow: o.flow, id: o.agent.id, task: o.agent.task ?? null, label: o.agent.task || o.agent.title || o.agent.id, machines: all.map((b) => b.machine) });
    const top = scene!.top!, steps = traceSteps(sky.flows, all, top.machine, ensureMled()?.ledgerHas ?? (() => false));
    const colOf = (m: string) => {
      const init = sky.flows[m]?.machine.states.find((s) => s.initial)?.id ?? sky.flows[m]?.machine.states[0]?.id;
      return (m === top.machine ? scene!.mStates[init ?? ""]?.color : top.rows.find((r) => r.name === m)?.nodes.find((n) => n.id === init)?.color) ?? RAMP[2];
    };
    panel.innerHTML = `<span class="x">✕</span><h2>${esc(o.agent.task || o.agent.title)}</h2><div class="k">${esc(boardTitle(o.agent) || o.agent.title || "")}</div>
      <table>${all.map((b) => `<tr class="mrow"><td><i style="background:${colOf(b.machine)}"></i>${esc(b.machine)}</td><td>${esc(stName(b.machine, b.agent.state))}</td><td style="text-align:right;color:#6b7a93">${hhmm(b.agent.active ?? 0)}</td></tr>`).join("")}</table>
      <div class="k" style="margin-top:10px">path · ${steps.length} steps, in order</div><table class="trace">${steps.map((s) => `<tr><td>${s.n}</td><td>${s.kind === "entry" ? `<b>${esc(s.b.machine)}</b> <span class="k">entered from ${esc(stName(s.a.machine, s.a.state))}</span>` : `${esc(stName(s.a.machine, s.a.state))} → ${esc(stName(s.b.machine, s.b.state))} <span class="k">${esc(s.b.machine)}</span>`}</td><td>${hhmm(s.at)}</td></tr>`).join("")}</table>`;
    openPanel();
  }
  function click(fx: number, fy: number) {
    const h = hover, sky = S;
    const rail = scene?.top ? railHit(fx - view.x, fy) : null;
    if (rail) return railClick(rail);
    if (h?.kind === "state" && scene?.top && h.o.machine === scene.top.machine && sky) {
      const to = firstOpened(sky.flows, scene.top.ranked, h.o.machine, h.o.id);
      if (to) revealRow(to); // a state of the top scrolls to the first machine it opens, and picks it out
      return to ? setFocus(to) : undefined;
    }
    if (!h || !sky) return void closePanel();
    // a click anywhere on a row (its name, a state or a DAG star) opens that machine, nested or not
    if (h.kind === "row") return drill(h.o.name, fx, fy);
    if (h.kind === "rstate") return drill(scene!.top!.rows.find((r) => r.nodes.includes(h.o))!.name, fx, fy);
    pin = null;
    if (h.kind === "ltask") return openLedgerTask(h.o);
    pinLedger(null);
    if (h.kind === "galaxy") return push({ kind: "state", id: h.o.id }, fx, fy);
    // a hangar drills into the Ledger of its DAGs, one level down like a state, so a right-click comes back; an orbiter opens the Ledger of its tie
    if (h.kind === "pivot") return push(hangarLevel(boardSource(), h.o.orbs), fx, fy);
    if (h.kind === "tie") {
      const t = tieLedger(boardSource(), h.o);
      return t ? push(t.led, fx, fy) : undefined;
    }
    if (h.kind === "moon" && h.o.pager) return changePage(h.o.pager);
    if (h.kind === "planet" && h.o.pager) return changePage(h.o.pager);
    if (h.kind === "planet") return push({ kind: "machine", flow: h.o.subState ? h.o.flow! : h.o.name }, fx, fy);
    // a moon opens its machine, and so does one of its sub-states (the machine the sub-state belongs to; its child opens from there)
    if (h.kind === "moon" || h.kind === "sat") return go([...path, { kind: "state", id: h.o.parent.id }, { kind: "machine", flow: h.kind === "moon" ? h.o.name : h.o.machine }], fx, fy);
    if (h.kind === "caption") return openDagPanel(scene!.stars[h.o.dag]);
    if (h.kind === "lrow") return openMerge(h.o);
    if (h.kind === "lstep") return starOfStep(h.o) ? openDagPanel(starOfStep(h.o)!) : undefined;
    if (h.kind === "ljunction" || h.kind === "ldoctor") return;
    // a Board path opens its Ledger when a DAG writes one of its events or is cued by it
    const ledger = h.kind === "bedge" ? ledgerOfEdge(h.o) : null;
    if (ledger) return push(ledger, fx, fy);
    if (h.kind === "dag") return openDagPanel(h.o);
    const at = subjectOf(h);
    if (at && pinnable(at)) pin = at;
    if (h.kind === "task") panel.innerHTML = taskPanel(h.o, sky, stateName);
    else if (h.kind === "mtask") {
      const o = h.o;
      panel.innerHTML = `<span class="x">✕</span><div class="k">${esc(taskKicker(o.machine, o._state || o.state, sourceOf(o.machine)))}</div><h2>${esc(o.id)} — ${esc(o.title)}</h2>
        <table>${(o.trail ?? []).slice(-12).map((t) => `<tr><td>${hhmm(t.at)}</td><td>${esc(t.event)} → ${esc(t.state)}</td></tr>`).join("")}</table>`;
    } else return;
    // the hop table sits under the facts, above the board link
    const note = panel.querySelector(".note");
    if (pin && note) note.insertAdjacentHTML("beforebegin", SLOT);
    else if (pin) panel.insertAdjacentHTML("beforeend", SLOT);
    openPanel();
    paintTable();
  }

  // ---- drawing ----
  /** The value `key` shows on this level, eased from the one it showed when a snapshot changes it: the Board's places, sky and sizes and a
   *  state's sun take it as the level is laid out (`layout`), so their tasks, paths and neighbours move with them; a machine's states draw at it. */
  const sized = (key: string, r: number) => grown.of(`${pathKey(path)}|${key}`, r, performance.now());
  const sourceOf = (flow: string | null | undefined) => (flow ? S?.flows[flow]?.machine.source ?? undefined : undefined);
  // The DAGs tied to a Board state (D7b): a hangar per state, its DAGs orbiting the state's ring, each turned toward the transition it acts on.
  const tieCache = new WeakMap<Scene, Ties>();
  function ties(): Ties | null {
    const sc = scene;
    if (!sc || !S || level().kind !== "board") return null;
    const u = 1 / fit.k, ts = (prefs().scale / 100) * (sc.labelScale ?? 1);
    let t = tieCache.get(sc);
    if (!t || t.u !== u || t.ts !== ts) tieCache.set(sc, (t = boardTies(sc, S, u, ts)));
    return t;
  }
  const boardDrawing = boardDraw(dc, pen, {
    get S() { return S; }, get scene() { return scene; }, get T() { return T; }, moves, get liveTasks() { return liveTasks; }, get hotEdge() { return hotEdge; },
    events: () => EVENTS(), moving, sized, sourceOf, ties, heldRows, focused,
  });
  const foldIO = {
    get S() { return S; }, get scene() { return scene; }, get T() { return T; }, get onFold() { return !trans && level().kind === "fold"; }, moves, get hotEdge() { return hotEdge; },
    contract, rerunStore, hhmm, prefs, heldRows, focused, openRow, wake: () => loop.wake(), get doctor() { return doctor; }, set doctor(v) { doctor = v; },
  };
  ensureFold = (): FoldDrawing | null => {
    if (foldDrawing) return foldDrawing;
    void loadFold().then((mod) => {
      if (!foldDrawing) foldDrawing = mod.foldDraw(dc, pen, foldIO);
      loop.wake();
    });
    return null;
  };
  const { drawTrace, drawSource, planetName } = traceDraw(dc, pen, {
    get S() { return S; }, get scene() { return scene; }, get hover() { return hover; }, get pin() { return pin; }, get mouse() { return mouse; },
    get spotted() { return spotted; }, get W() { return W; }, get H() { return H; }, level, pinnable, runFor, sourceOf,
  });
  // ---- the machine ledger's scroll, the footer that loads older machines, and the 24 h strip along the bottom ----
  let railHover: Rail | null = null, railMoving = false;
  /** What the rail is under (x, y) of the ledger: the back-to-newest chip, the thumb, a tick of the strip or the footer. */
  function railHit(x: number, y: number): Rail | null {
    if (!scene?.top) return null;
    const led = ensureMled();
    if (!led) return null;
    const r = led.railBox, within = (b: { x0: number; y0: number; x1: number; y1: number } | null) => !!b && x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1;
    if (within(r.chip)) return { kind: "chip" };
    if (led.thumb && Math.abs(x - r.thumbX) < 8 && y > r.laneTop + led.thumb.y0 && y < r.laneTop + led.thumb.y1) return { kind: "thumb" };
    if (y >= r.stripT) {
      const t = x < r.sx0 - 4 || x > r.sx1 + 4 ? null : tickAt(led.ticks, x);
      return t ? { kind: "tick", tick: t } : null;
    }
    return within(r.foot) ? { kind: "foot" } : null;
  }
  /** Move the scroll's goal by an input; false for a key that does not scroll. */
  function scrollBy(input: ScrollInput): boolean {
    const top = scene?.top;
    if (!top) return false;
    const to = inputGoal(input, scrollGoal, { h: top.laneBottom - top.laneTop, fs: ledgerSizes(prefs().scale).fs }, top.max);
    if (to === null) return false;
    scrollGoal = to;
    return true;
  }
  /** Scroll the machine's row to the middle of the lane, bringing in the older machines between it and the page held if it is not loaded. */
  function revealRow(name: string) {
    if (pg) {
      pg = reveal(pg, S!.flows[name]?.last ?? 0);
      layout(true);
    }
    const top = scene!.top!, i = top.rows.findIndex((r) => r.name === name);
    if (i >= 0) scrollGoal = revealGoal(top.rows, i, { h: top.laneBottom - top.laneTop, fs: ledgerSizes(prefs().scale).fs }, top.max);
    loop.wake();
  }
  /** The next 20 older machines: asked once for a footer in view, and again a few seconds after a failure. */
  function loadNext() {
    const p = pg;
    if (!p?.more || p.busy) return;
    pg = asked(p);
    apiFetch(nextQuery(p))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((b: { machines: { name: string; last: number | null }[]; more: boolean }) => {
        if (pg?.top !== p.top) return;
        pg = pageArrived(pg, b.machines, b.more);
        layout(true);
        loop.wake();
      })
      .catch(() => {
        if (pg?.top === p.top) pg = failed(pg, Date.now() / 1000);
        window.setTimeout(() => loop.wake(), RETRY * 1000 + 100);
      });
  }
  function railClick(r: Rail) {
    if (r.kind === "chip") scrollGoal = 0;
    else if (r.kind === "tick") revealRow(r.tick.entry.row);
    else if (r.kind === "foot") loadNext();
    loop.wake();
  }
  /** One frame of the scroll: ease to the goal, and ask for the next page when the footer is in view. */
  function scrollStep() {
    const top = scene!.top!, d = scrollGoal - scrollPos;
    scrollPos = Math.abs(d) < 0.5 ? scrollGoal : scrollPos + d * 0.3;
    railMoving = scrollPos !== scrollGoal;
    if (wantNext(pg, top.more > 0 && top.laneTop + top.content - top.foot - scrollPos < top.laneBottom, T)) loadNext();
  }
  let rowsHeld = false;
  const overRows = () => !!(mouse && scene?.top && mouse.oy > scene.top.laneTop && mouse.oy < scene.top.laneBottom);
  function drawScene(k: number, x: number, y: number) {
    const dpr = devicePixelRatio || 1;
    cx.setTransform(k * dpr, 0, 0, k * dpr, x * dpr, y * dpr);
    K = k;
    ZS = Math.max(1, k / fit.k);
    if (scene!.top) return void ensureMled()?.drawTop();
    if (scene!.fold) ensureFold()?.drawFold();
    boardDrawing.drawGalaxies();
    boardDrawing.drawMoons();
    boardDrawing.drawBoardEdges();
    drawBranches(dc, pen, scene!);
    boardDrawing.drawTies();
    boardDrawing.drawStateLinks();
    boardDrawing.drawSun();
    boardDrawing.drawPlanets();
    boardDrawing.drawTasks();
    boardDrawing.drawMachineEdges(scene!.mEdges);
    boardDrawing.drawStates(scene!.mStates, true);
    drawSource();
    boardDrawing.drawMachineTasks();
    boardDrawing.drawStars();
    drawTrace();
  }
  let wash: { w: number; h: number; g?: CanvasGradient } = { w: 0, h: 0 };
  let shown1 = false;
  const frame = (now: number) => {
    if (away) return; // the canvas is hidden behind another view
    // The ambient clock (orbits, twinkle, dash drift) advances only across frames drawn back to back, so it freezes at rest and resumes where it stopped.
    clock += last ? Math.min(now - last, 100) / 1000 : 0;
    last = now;
    T = Date.now() / 1000;
    if (scene && (grown.growing() || ((scene.fold || scene.top) && laidScale !== prefs().scale))) layout(true); // a state easing to a new size moves its neighbours, paths and the fit with it, frame by frame
    if (scene?.top && (overRows() || !!lpin) !== rowsHeld) {
      rowsHeld = !rowsHeld;
      layout(true); // the order holds from the row the pointer entered, or while a path is pinned, and is released to the newest-first order after
    }
    if (scene?.top) {
      scrollStep();
      railHover = mouse && !trans ? railHit(mouse.ox - view.x, mouse.oy) : null;
    }
    if (anim) anim(now);
    if (scene) update(clock);
    if (mouse && scene) setHover(hit((mouse.ox - view.x) / view.k, (mouse.oy - view.y) / view.k), mouse.cx, mouse.cy);
    else if (spotted && scene && !trans) {
      // a rail spot is a hover without a pointer: its card sits beside the spotted body, where a pointer on it would put it, and steps
      // aside once a click opens the panel, which the pointer resting on the rail would otherwise leave it covering
      const h = (spotIn(scene, spotted) ?? (spotNear && spotted.kind === "task" ? spotIn(scene, { kind: "state", id: spotted.lane }) : null)) as Hover | null;
      const at = h?.o as Partial<Pt> | undefined;
      setHover(h, L + view.x + (at?.x ?? 0) * view.k, view.y + (at?.y ?? 0) * view.k);
      if (panel.classList.contains("open")) tip.style.opacity = "0";
    }
    const dpr = devicePixelRatio || 1;
    cx.globalAlpha = 1;
    cx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // the current board's night sky: a radial wash and 160 slow-twinkling stars with a slight parallax against the view
    if (wash.w !== W || wash.h !== H) {
      wash = { w: W, h: H, g: cx.createRadialGradient(W * 0.5, H * 0.55, 0, W * 0.5, H * 0.55, Math.max(W, H) * 0.75) };
      wash.g!.addColorStop(0, "#0e1628");
      wash.g!.addColorStop(1, "#04060b");
    }
    cx.fillStyle = wash.g!;
    cx.fillRect(0, 0, W, H);
    for (const s of STARS) {
      cx.fillStyle = `rgba(200,215,240,${0.08 + 0.12 * (0.5 + 0.5 * Math.sin(clock * 0.6 + s.p))})`;
      cx.beginPath();
      cx.arc(s.x * W, (((s.y * H + view.y * 0.06 * s.r) % H) + H) % H, s.r, 0, TAU);
      cx.fill();
    }
    if (scene) {
      if (!trans) drawScene(view.k, view.x, view.y);
      else {
        // in: the old level blows up through the clicked point and fades; the new one grows out of it. out: the reverse
        const q = Math.min(1, (now - trans.t0) / 520), e = ease(q), f = trans.f;
        const sNew = trans.inward ? 0.3 + 0.7 * e : 2.6 - 1.6 * e, sOld = trans.inward ? 1 + 2.5 * e : 1 - 0.7 * e;
        cx.globalAlpha = e;
        drawScene(view.k * sNew, f.x + sNew * (view.x - f.x), f.y + sNew * (view.y - f.y));
        cx.globalAlpha = 1 - e;
        cx.setTransform(dpr, 0, 0, dpr, 0, 0);
        cx.drawImage(trans.snap, f.x * (1 - sOld), f.y * (1 - sOld), W * sOld, H * sOld);
        cx.globalAlpha = 1;
        if (q >= 1) trans = null;
      }
    }
    if (scene && !trans && onDrawn && !shown1) {
      shown1 = true;
      onDrawn();
      extrasCancel ??= prefetchBoardExtras();
      const afterPaint = () => {
        void loadLedgerPanel();
        void loadHudViews().then(() => { if (!stopped) publish(); });
      };
      if (typeof requestIdleCallback === "function") requestIdleCallback(afterPaint, { timeout: 2000 });
      else setTimeout(afterPaint, 0);
    }
    if (now - tick > 250) {
      tick = now;
      heartbeat();
    }
  };
  /** Something still needs the next frame: a move or DAG run in flight, a fly-to, a level transition, or a body easing to a new size. */
  const busy = () => !away && !!S && (animating({ now: T, moves: EVENTS(), dags: S.dags, flying: !!anim, transitioning: !!trans }) || grown.growing() || !!mled?.sliding || !!foldDrawing?.scrolling() || railMoving || gliding || SIM);
  /** The loop settled: the feed and moving list get their last write, and the next wake starts the ambient clock afresh. */
  const settle = () => {
    last = 0;
    heartbeat();
  };
  // with Motion off the loop idles at one frame a second, except for a moment after any input
  let lastInput = -Infinity;
  const loop = frameLoop({ draw: frame, animating: busy, idle: settle, pace: () => framePace(prefs().motion, performance.now() - lastInput) });
  /** Every input that can change what the canvas shows wakes it; the handlers run first, so the frame sees their result. */
  const wakers: [EventTarget, string][] = [
    [window, "resize"], [window, "mousemove"], [window, "mouseup"], [window, "keydown"], [document, "visibilitychange"],
    [cv, "mousedown"], [cv, "mouseleave"], [cv, "contextmenu"], [cv, "wheel"],
  ];
  const wake = () => {
    lastInput = performance.now();
    loop.wake(true);
  };

  const probe = (): Probe => {
    const sc = scene, l = level(), canvas = { w: W, h: H }, open = panel.classList.contains("open");
    if (!sc) return { path: pathKey(path), ready: false, canvas, panel: open, centre: { x: 0, y: 0 }, zoomed: false, targets: [], fit: fit.k, states: [] };
    const [x0, y0, x1, y1] = sc.box ?? [0, 0, sc.w, sc.h], at = (name: string, p: Pt, opens: Probe["targets"][number]["opens"] = "level") => ({ name, opens, ...toScreen(view, p) });
    const targets = l.kind === "board"
      ? [
          ...Object.values(sc.galaxies).map((g) => at(g.id, g)),
          ...sc.moons.map((m) => at(m.name, m)),
          ...sc.subStates.map((b) => at(`${b.machine}/${b.state}`, b)),
          ...sc.tasks.filter((t) => !t.gone).map((t) => at(t.id, t, "panel")),
        ]
      : l.kind === "fold" ? Object.values(sc.stars).map((s) => at(s.name, s, "panel"))
      : [
          ...sc.planets.filter((p) => l.kind === "state" || p.anchor).map((p) => at(p.name, p)),
          ...(l.kind === "machine" ? sc.machineTasks.filter((t) => t._x !== undefined).map((t) => at(t.id, { x: t._x!, y: t._y! }, "panel")) : []),
        ];
    const board = l.kind === "board";
    const states = board ? Object.values(sc.galaxies).map((g) => ({ id: g.id, ...toScreen(view, g), r: g.R * view.k, sun: g.r * view.k, edge: g.edge * view.k })) : [];
    const edges = board ? sc.bEdges.filter((e) => e.p0 && e.c && e.p1).map((e) => ({ s: e.source, t: e.target, pts: Array.from({ length: 21 }, (_, i) => toScreen(view, bez(e.p0!, e.c!, e.p1!, i / 20))) })) : [];
    return { path: pathKey(path), ready: !trans && !anim, canvas, panel: open, centre: toScreen(view, { x: (x0 + x1) / 2, y: (y0 + y1) / 2 }), zoomed: zoomedIn(view, fit), targets, fit: fit.k, states, edges, branches: board ? branchLines().map((b) => ({ ...b, pts: b.pts.map((p) => toScreen(view, p)) })) : [], tasks: sc.tasks.filter((t) => !t.gone).map((t) => ({ id: t.id, ...toScreen(view, t) })), texts: board ? textHits(sc) : [] };
  };

  return {
    start() {
      addEventListener("resize", onResize);
      document.addEventListener("visibilitychange", onVisibility);
      addEventListener("mousemove", onMove);
      addEventListener("mouseup", onUp);
      addEventListener("keydown", onKey);
      cv.addEventListener("mousedown", onDown);
      cv.addEventListener("mouseleave", onLeave);
      cv.addEventListener("contextmenu", onContext);
      cv.addEventListener("wheel", onWheel, { passive: false });
      (window as unknown as { flowProbe: () => Probe }).flowProbe = probe;
      for (const [target, type] of wakers) target.addEventListener(type, wake);
      resize();
      loop.wake();
      // the first layout measures label widths and the first frame draws them: both wait for the page's fonts, which index.html preloads
      void loadFonts().then(() => {
        if (!stopped) stream = openStream(connection);
      });
      fanTimer = window.setInterval(paintFan, 1000);
    },
    stop() {
      stopped = true;
      extrasCancel?.();
      extrasCancel = null;
      publishLater.cancel();
      loop.stop();
      stream?.close();
      ledgerOpen?.stream.close();
      ledgerOpen = null;
      cancelReload?.();
      clearTimeout(timer);
      clearInterval(timer);
      clearInterval(fanTimer);
      clearTimeout(saveT);
      for (const [target, type] of wakers) target.removeEventListener(type, wake);
      removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
      removeEventListener("mousemove", onMove);
      removeEventListener("mouseup", onUp);
      removeEventListener("keydown", onKey);
      cv.removeEventListener("mousedown", onDown);
      cv.removeEventListener("mouseleave", onLeave);
      cv.removeEventListener("contextmenu", onContext);
      cv.removeEventListener("wheel", onWheel);
    },
    go: (p, fx, fy, then) => {
      relay.settle();
      if (S) go(p, fx, fy, then);
    },
    fitView: () => {
      relay.settle();
      if (scene) flyTo(fit);
    },
    show(on) {
      away = !on;
      relay.show(on);
    },
    spot(target, near = false) {
      spotted = target;
      spotNear = near;
      if (!target) setHover(null);
      loop.wake();
    },
    refresh() {
      if (!S) return;
      publishLater.cancel();
      write(compose());
      heartbeat();
    },
    openTask(id) {
      relay.settle();
      if (!S || !scene) return;
      const h = spotIn(scene, { kind: "task", id, lane: "" }) as Hover | null, raw = S.board.agents.find((a) => a.id === id);
      if (h) {
        hover = h;
        click(W / 2, H / 2);
      } else if (raw) {
        pin = null;
        panel.innerHTML = taskPanel(raw, S, stateName);
        openPanel();
      }
      loop.wake();
    },
    selectTask(id) {
      relay.settle();
      if (!S) return;
      if (level().kind !== "board") go(BOARD);
      const h = spotIn(scene!, { kind: "task", id, lane: "" }) as Hover | null;
      if (!h) return;
      hover = h;
      click(W / 2, H / 2);
      loop.wake();
    },
  };
}
