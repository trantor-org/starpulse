// The canvas side of the page, ported from the approved round-13 mockup
// (the design mockup): it takes the Board and the runs instances from the
// server's event stream (every machine's tasks and the runs instances' workflows), merges them into one sky,
// lays the current level out with scene.ts, plays each move once as the
// mockup's replay did, and owns the level stack, the view, the tooltip and the
// click panels. It draws only while something animates (idle.ts).
// Click drills in, right-click steps out (after clearing any zoom), the wheel
// zooms about the cursor between the level's fit and eight times it, and a drag
// pans only while zoomed in. The path and each level's zoom are kept per browser.
import { demoStep } from "./demo";
import type { FeedLine, HudState, HudStore } from "./hud";
import { animating, frameLoop, framePace } from "./idle";
import { BOARD, drill, pathKey, startPath, type Level, type Path } from "./levels";
import { spotIn, type Target } from "./search";
import {
  BOARD_COLOR, GALAXY_MIN, OWNED, TAU, bez, terminal, build, clip, curveDist, curveOf, edgePaths, nearestWithin, stateR, taskSlot, tethersDrawn, textW, turnPage,
  type BEdge, type Body, type Curve, type Galaxy, type Hangar, type Hop, type MEdge, type MState, type Planet, type Pt, type Scene,
  type MachineTask, type Moon, type Pager, type Star, type SubState, type Sun,
} from "./scene";
import { FLARE, Moves, PULSE, TRAVEL, merge, type Move, type Sky } from "./sky";
import { kanbanTasks } from "./kanban";
import { embedded, openStream } from "./stream";
import { createHistory } from "./history";
import { sizes } from "./grow";
import { draws, hostRun, laneRun, layout as traceLayout, machineRun, sessionRings, subjectOf, traceCard, traceTable, type Place, type Run, type Subject } from "./trace";
import type { Dag, Machine, Snapshot, Writer } from "./types";
import { esc, startRun, taskPanel } from "./panels";
import { ADMIN_DEFAULTS, labelPx, type AdminPrefs } from "./adminPrefs";
import { clockHm, clockHms, stamp } from "./clock";
import { canvasSpace, retired, viewOf, viewSearch } from "./nav";
import { fitBox, fitLevel, refitView, toScreen, wheelFactor, zoomAbout, zoomedIn, type View } from "./zoom";

const DAG_COLOR: Record<string, string> = { running: "#fbbf24", queued: "#93c5fd", succeeded: "#34d399", failed: "#fb7185",
  aborted: "#94a3b8", skipped: "#64748b", not_started: "#334155" };
/** Declared step kind rings on a DAG's level. */
/** Activity: everything that moves on any level uses this one colour. */
const ACT = "#fbbf24";
/** An agent is coloured by the tier its profile names (`@agent-<tier>-<effort>`); a person or fast is the other colour. */
export const tierColor = (profile = "") =>
  profile.startsWith("@agent-deep") ? "#c4b5fd" : profile.startsWith("@agent-standard") ? "#67e8f9" : "#fde68a";
const rgba = (h: string, a: number) => {
  const n = parseInt(h.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
};
const ease = (u: number) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
/** The current board's ease-out for a hop. */
const easeO = (u: number) => 1 - Math.pow(1 - u, 3);
const finished = (iso: string) => (iso ? Date.parse(iso) / 1000 : NaN);

/** The ring a DAG's run ending at `fin` has on screen at `now`, as its age from 0 to 1: one ring per event, over PULSE, never repeated. */
/** The ring an arrival shows at `age`, 0 to 1 over PULSE: one ring, never a second a beat behind it. */
export const arrivalRings = (age: number): number[] => (age > 0 && age < 1 ? [age] : []);
export const dagRings = (fin: number | undefined, now: number): number[] =>
  fin !== undefined && fin <= now && now - fin < PULSE ? [(now - fin) / PULSE] : [];

// Browser storage can be absent (a private window) or hold anything; the page works without it.
function recall<T>(key: string): T | null {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "null") as T | null;
  } catch {
    return null;
  }
}
function keep(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage is off: the page just forgets
  }
}

// the seeded night sky and its twinkle, the same as the current board's backdrop
let seed = 7;
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const STARS = Array.from({ length: 160 }, () => ({ x: rnd(), y: rnd(), r: rnd() * 1.1 + 0.2, p: rnd() * TAU }));

type Hover =
  | { kind: "mtask"; o: MachineTask }
  | { kind: "task"; o: Body }
  | { kind: "dag"; o: Star }
  | { kind: "hangar"; o: Hangar }
  | { kind: "state"; o: MState }
  | { kind: "planet"; o: Planet }
  | { kind: "sun"; o: Sun }
  | { kind: "galaxy"; o: Galaxy }
  | { kind: "moon"; o: Moon }
  | { kind: "sat"; o: SubState }
  | { kind: "medge"; o: MEdge }
  | { kind: "bedge"; o: BEdge }
  | { kind: "link"; o: Hop };

/** What the Playwright probe reads: the level, where its box sits on screen, and what a click there opens. */
export interface Probe {
  path: string;
  /** Whether a snapshot has arrived and no transition or fly-to is running. */
  ready: boolean;
  /** The canvas the level is centred in; an open panel floats over it. */
  canvas: { w: number; h: number };
  /** Whether a click panel is open. */
  panel: boolean;
  centre: Pt;
  zoomed: boolean;
  /** What a click opens: another level, or a panel beside this one. */
  targets: { name: string; opens: "level" | "panel" | "none"; x: number; y: number }[];
  /** The level's fit zoom. */
  fit: number;
  /** Board only: each DAG glyph's screen box, each state's screen disc, and the screen centre of the DAGs hangar (null when no DAG is free of the Board). */
  dags: { name: string; x0: number; y0: number; x1: number; y1: number }[];
  states: { id: string; x: number; y: number; r: number }[];
  hangar: Pt | null;
}

export interface Renderer {
  start(): void;
  stop(): void;
  /** Open a level; the old one zooms through (fx, fy). `then` gives the view to land on. */
  go(path: Path, fx?: number, fy?: number, then?: () => View): void;
  /** Fly back to the level's fit. */
  fitView(): void;
  /** The canvas is the page again after another view hid it: resize it and refit, keeping a zoomed-in view. */
  resize(): void;
  /** Open a DAG's panel beside the level that is showing. */
  openDag(name: string): void;
  /** Fly to a domain's DAGs on the Board. */
  flyToGroup(name: string): void;
  /** Light the body a navigator search result stands for, as a hover over it would; null clears it. */
  spot(target: Target | null): void;
  /** Pin a task on the Board and open its panel, as a click on it would. */
  selectTask(id: string): void;
  /** The Admin view changed how times are written: write the subtitle, the Recent feed and the header clock again. */
  refresh(): void;
}

export function renderer(cv: HTMLCanvasElement, hud: HudStore, els: { tip: HTMLElement; panel: HTMLElement; clock: HTMLElement }, demo: boolean, prefs: () => AdminPrefs = () => ADMIN_DEFAULTS): Renderer {
  const cx = cv.getContext("2d")!, { tip, panel } = els;
  const hhmm = (sec: number) => clockHm(sec, prefs().clock);
  let S: Sky | null = null, snap: Snapshot | null = null, scene: Scene | null = null;
  const moves = new Moves();
  let path: Path = BOARD, W = 0, H = 0, view: View = { k: 1, x: 0, y: 0 }, fit: View = view;
  // the task whose path a click pinned, kept by id so each frame finds it again in the rebuilt scene
  let pin: Subject | null = null;
  const pages: Record<string, number> = {};
  // what a navigator search result under the pointer stands for, lit while the pointer is off the canvas
  let spotted: Target | null = null;
  let hover: Hover | null = null, mouse: { ox: number; oy: number; cx: number; cy: number } | null = null;
  let trans: { snap: HTMLCanvasElement; inward: boolean; f: Pt; t0: number } | null = null, anim: ((now: number) => void) | null = null;
  let drag: { fixed: boolean; x: number; y: number; vx: number; vy: number; moved: boolean } | null = null;
  // ZS: zoom beyond the fit size; K: absolute zoom. Text, pulses and dashes divide by these so they never balloon.
  const grown = sizes(), bends = new Map<string, Pt>(); // each bent Board path's last bend, so it keeps its route while that clears
  let T = Date.now() / 1000, clock = 0, liveTasks = new Set<string>(), hotEdge = new Set<string>(), ZS = 1, K = 1;
  let timer = 0, clockTimer = 0, stopped = false, saveT = 0, tick = 0, clockText = "", live: "" | "on" | "off" = "";
  // The stream the page reads its snapshot and every change after it from.
  let stream: { close(): void } | null = null, last = 0;

  // A self-contained demo page: its embedded snapshot already holds every flow, and its address is not the server's.
  const fixture = embedded() !== null;
  const level = (): Level => path[path.length - 1];
  const stateName = (id: string) => S?.board.machine.states.find((s) => s.id === id)?.name || id;
  const EVENTS = () => moves.events;
  const moving = (flow: string) => EVENTS().filter((e) => e.flow === flow && e.from && e.at <= T && T - e.at < TRAVEL);
  const cueLine = (n: string) => (S?.cues ?? []).filter((c) => c.dag === n).map((c) => `runs on ${esc(c.on)}, beside ${esc(c.event)}`).join("; ");
  const writes = (n: string) => Object.entries(S!.writers).filter(([, ws]) => ws.some((w) => w.actor === n)).map(([ev]) => ev);

  // ---- view: scroll zooms about the cursor (scale only, never changes level), drag pans; kept per screen size and level ----
  const railW = () => document.getElementById("rail")?.offsetWidth ?? 0;
  // the panel's open and folded widths, never its current one, so a fold neither resizes the canvas nor moves a body
  const navWidths = () => {
    const css = getComputedStyle(document.documentElement), px = (v: string) => parseFloat(css.getPropertyValue(v)) || 0;
    return { open: px("--nav"), fold: px("--nav-fold") };
  };
  // the canvas is the page between the navigator and the rail, so its size (not the window's) keys the remembered zoom
  const viewKey = () => `fv.view.${W}x${H}.${pathKey(path)}.${scene?.w}x${scene?.h}`;
  // the default view fits the level's content box (the whole sky on the Board), centred between the open navigator and the
  // rail, `I` from the canvas's left edge; a panel floats over it
  const inFitBox = (v: View): View => ({ ...v, x: v.x + I });
  const fitScene = (): View => inFitBox(fitLevel(scene!, FW, H));
  /** Lay the level out for the canvas's shape, so a wider screen spreads it instead of framing it with empty sky. */
  function layout(keepView: boolean) {
    if (!S || !W) return;
    const was = fit;
    scene = build({ S, moves, W: FW, H, T, pages, ease: sized, routes: bends }, level());
    fit = fitScene();
    if (scene.hub) edgePaths(scene, { k: fit.k, x: fit.x - I }, FW, stateName);
    if (keepView) view = refitView(view, was, fit); // a view at the old fit follows the new one, so the sky zooms out smoothly as a state grows
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
  // the canvas's left edge on the page (the folded navigator's width); the fit box's offset in it and its width
  let L = 0, I = 0, FW = 0;
  const resize = (keepView = false) => {
    const dpr = devicePixelRatio || 1;
    ({ left: L, width: W, inset: I, fitWidth: FW } = canvasSpace(innerWidth, navWidths(), railW()));
    H = innerHeight;
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
    const inward = next.length >= path.length;
    path = next;
    keep("fv.path", path);
    pin = null;
    panel.classList.remove("open");
    setHover(null);
    anim = null;
    layout(false);
    if (then) view = then();
    hud.set({ path });
    trans = { snap: shot, inward, f: { x: fx, y: fy }, t0: performance.now() };
    loop.wake();
  }
  const zoomedOut = () => view.k <= fit.k * 1.02;
  const push = (l: Level, fx: number, fy: number) => go([...path, l], fx, fy);
  // step out: first undo any zoom, then (already at the default size) go up one level; at the top level it only clears zoom
  const pop = (fx?: number, fy?: number) => {
    if (!zoomedOut()) return flyTo(fit);
    if (path.length > 1) go(path.slice(0, -1), fx, fy);
  };

  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    if (trans || !scene) return;
    anim = null;
    view = zoomAbout(view, fit, { x: e.offsetX, y: e.offsetY }, wheelFactor(e.deltaY, e.deltaMode, H)) ?? fit;
    save();
  };
  // right-click closes an open panel and stays on the level; with none open it steps out
  const onContext = (e: MouseEvent) => {
    e.preventDefault();
    if (!closePanel()) pop(e.offsetX, e.offsetY);
  };
  const onDown = (e: MouseEvent) => {
    if (e.button !== 0) return;
    drag = { fixed: zoomedOut(), x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
    cv.classList.add("drag");
  };
  const onUp = (e: MouseEvent) => {
    cv.classList.remove("drag");
    if (drag && !drag.moved && e.target === cv) click(e.offsetX, e.offsetY);
    drag = null;
  };
  const onMove = (e: MouseEvent) => {
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
    if (!mouse) setHover(null);
  };
  const onLeave = () => {
    mouse = null;
    setHover(null);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") closePanel();
    if (e.target instanceof HTMLInputElement) return;
    if (e.key === "Backspace") pop();
    if (e.key === "0" && scene) flyTo(fit);
  };
  /** A hidden tab stops animating, so it drops the stream; on return the stream's fresh snapshot places everyone at once, replaying nothing missed. */
  const onVisibility = () => {
    if (demo) return;
    if (document.hidden) {
      stream?.close();
      stream = null;
      moves.resync();
    } else stream ??= openStream({ snapshot: onSnapshot, live: onLive });
  };

  // ---- data: every machine's tasks and the runs instances' workflows, pushed by the stream ----
  /** Each connect's snapshot and every delta after it, drawn at once. */
  function onSnapshot(next: Snapshot) {
    const first = !S;
    if (demo && snap) {
      snap = { ...snap, dags: next.dags }; // the demo plays the machines itself and keeps only the runs instances' workflows live
      return;
    }
    apply(next);
    if (first && demo && !stopped) timer = window.setTimeout(demoTick, 1200);
  }
  function onLive(on: boolean) {
    if (!on) moves.resync(); // the reconnect's snapshot places what the drop missed, as a returning tab's does
    live = on ? "on" : "off";
    hud.set({ live });
    paintClock();
  }
  const demoTick = () => {
    if (stopped || !snap) return;
    apply(demoStep(snap));
    timer = window.setTimeout(demoTick, 600 + Math.random() * 1200);
  };
  function apply(next: Snapshot) {
    const first = !S;
    snap = next;
    T = Date.now() / 1000;
    S = merge(next);
    moves.observe(S, T);
    if (first) {
      // A retired per-graph address opens its level; the page's one address is the root.
      path = startPath(location.pathname, location.hash, recall<Path>("fv.path"), S.tree);
      if (!fixture && retired(location.pathname, location.hash)) history.replaceState(null, "", "/" + viewSearch(location.search, viewOf(location.search), prefs().view));
      keep("fv.path", path);
    }
    layout(!first);
    publish();
    loop.wake();
  }
  /** What the HUD shows, written once per snapshot. */
  function publish() {
    const sky = S!, board = sky.board;
    const at = stamp(sky.now, prefs().clock);
    const next: Partial<HudState> = {
      path,
      tree: sky.tree,
      stats: sky.error ? `live · ${at} MST · ${sky.error}` : `live · ${at} MST`,
      states: board.machine.states.map((s) => ({ id: s.id, name: s.name, count: board.agents.filter((a) => a.state === s.id).length })),
      counts: Object.fromEntries(Object.values(sky.flows).map((f) => [f.name, f.agents.length])),
      dags: sky.dags.map((d) => d.name),
      groups: sky.groups.map((g) => ({ name: g.name, n: g.dags.length })),
      cards: kanbanTasks(sky),
      names: Object.fromEntries(board.machine.states.map((s) => [s.id, s.name])),
      claims: sky.claims,
      boardUrl: sky.boardUrl,
    };
    // a delta rarely changes what the HUD shows, so only changed fields reach React and an unchanged HUD does not re-render
    const now = hud.get() as unknown as Record<string, unknown>;
    const changed = Object.fromEntries(Object.entries(next).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(now[k])));
    if (Object.keys(changed).length) hud.set(changed);
  }
  /** Every quarter second: the feed and the navigator's moving machines, written only when they change. */
  function heartbeat() {
    if (!S) return;
    const ev: Omit<FeedLine, "time">[] = EVENTS().filter((e) => e.at <= T).map((e, i) => ({ key: `m${i}`, at: e.at, who: e.task ?? "", what: e.event.toLowerCase(), where: e.flow }));
    for (const d of S.dags) {
      const f = finished(d.finishedAt);
      if (f <= T) ev.push({ key: `d${d.name}`, at: f, who: d.name, what: "", where: d.status });
    }
    ev.sort((a, b) => b.at - a.at);
    const feed: FeedLine[] = ev.slice(0, 40).map((l) => ({ ...l, time: hhmm(l.at) })), mv = [...new Set(EVENTS().filter((e) => e.from && e.at <= T && T - e.at < TRAVEL).map((e) => e.flow))].sort();
    const now = hud.get();
    if (feed.map((f) => f.key + f.at + f.time).join() !== now.feed.map((f) => f.key + f.at + f.time).join()) hud.set({ feed });
    if (mv.join() !== now.moving.join()) hud.set({ moving: mv });
  }

  // ---- motion: every orbiting body is placed from the clock each frame ----
  function update(t: number) {
    const sc = scene!, board = level().kind === "board";
    for (const l of [...sc.hops, ...sc.entries, ...sc.exits]) l.busy = false; // a path glows while a task travels it
    hotEdge = new Set(EVENTS().filter((e) => e.from && e.at <= T && T - e.at < TRAVEL).map((e) => `${e.flow}:${e.from}>${e.to}`));
    for (const k of sc.tasks) {
      const a = k.a0 + k.w * t, R = k.R;
      k.ang = a;
      k.x = k.host.x + Math.cos(a) * R;
      k.y = k.host.y + Math.sin(a) * R;
      k.moving = false;
      k.arrive = null;
      k.gone = false;
      k.via = null;
      if (!k.host.states && board) {
        // Board: a task sits on the state it held at this moment and hops along the transition's curve
        const bev = EVENTS().filter((e) => e.flow === "board" && e.task === k.id);
        if (!bev.length) continue;
        let st = bev[0].from ?? bev[0].to, ev: Move | null = null;
        for (const e of bev) if (e.at <= T) [st, ev] = [e.to, e];
        const g = sc.galaxies[st];
        if (!g) continue;
        if (g !== (k.host.parent ?? k.host)) {
          const va = k.a0 * 1.7 + k.w * t;
          k.x = g.x + Math.cos(va) * g.visR;
          k.y = g.y + Math.sin(va) * g.visR;
        }
        if (!ev || T - ev.at >= TRAVEL + PULSE) continue;
        const u = (T - ev.at) / TRAVEL, e = sc.bEdges.find((b) => b.source === ev.from && b.target === ev.to);
        if (!e) continue;
        if (u >= 1) {
          k.arrive = { x: g.x, y: g.y, r: g.r, col: g.color, age: (T - ev.at - TRAVEL) / PULSE };
          continue;
        }
        const q = bez(e.p0!, e.c!, e.p1!, easeO(u));
        k.x = q.x;
        k.y = q.y;
        k.moving = true;
        k.hop = { c: { p0: e.p0!, c: e.c!, p1: e.p1! }, u: easeO(u) };
        continue;
      }
      if (level().kind === "state" && stateHop(k, t)) continue;
      // a task whose machine is changing its state leaves its orbit, rides the machine's chord like the current board's hop (ease-out, comet tail),
      // rings the state it lands on, then drops back into orbit
      const st = k.host.states, ev = st && EVENTS().findLast((e) => e.task === k.id && e.flow === k.host.name && e.from && st[e.from] && st[e.to] && e.from !== e.to && e.at <= T && T - e.at < TRAVEL + PULSE);
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
    liveTasks = new Set(EVENTS().filter((e) => e.task && e.at <= T && T - e.at < TRAVEL).map((e) => e.task!));
  }

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
    const hostThen = (at: number) => !sc.hostAt || sc.hostAt(k.id, at) === k.host.name, hub = sc.hub!, onHub = k.host === hub;
    if (held !== sc.sid) {
      if (bs && bs.from === sc.sid && age < 1 && hostThen(bs.at)) {
        const to = bs.to, l = sc.exits.find((x) => x.target === to), via = `to ${stateName(to)}`;
        if (l && onHub) follow(k, l, age, via);
        else ride(k, orbitAt(k, back(bs)), l?.p1 ?? { x: sc.w * 2, y: hub.y }, age, via);
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
        if (l && onHub) follow(k, l, age, via);
        else ride(k, l?.p0 ?? { x: -sc.w, y: hub.y }, { x: k.x, y: k.y }, age, via);
        return true;
      }
      ring(bs.at);
    }
    if (!sc.hostAt) return !!k.arrive;
    const he = EVENTS().findLast((e) => e.task === k.id && e.at <= T && e.flow === ((k.host as Planet).machine ?? k.host.name)), prev = he && sc.hostAt(k.id, he.at - 0.001);
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
  function hit(x: number, y: number): Hover | null {
    const sc = scene!, near = (o: Pt, r: number) => Math.hypot(o.x - x, o.y - y) < r;
    for (const s of sc.machineTasks) if (s._x !== undefined && Math.hypot(s._x - x, s._y! - y) < Math.max(4, px(7))) return { kind: "mtask", o: s };
    for (const t of sc.tasks) if (!t.gone && near(t, Math.max(t.big ? 7 : 5, px(7)))) return { kind: "task", o: t };
    // a wide DAG's circle overlaps its docked neighbours, so the nearest DAG in range wins, not the first
    let star: Star | null = null, sd = Infinity;
    for (const s of Object.values(sc.stars)) {
      const d = Math.hypot(s.x - x, s.y - y);
      if (d < Math.max(s.br, px(10)) && d < sd) [star, sd] = [s, d];
    }
    if (star) return { kind: "dag", o: star };
    if (sc.hangar && near(sc.hangar, sc.hangar.r + 22)) return { kind: "hangar", o: sc.hangar };
    for (const s of Object.values(sc.mStates)) if (near(s, Math.max(stateR(s), px(9)))) return { kind: "state", o: s };
    for (const p of sc.planets) if (near(p, p.subState ? Math.max(p.R, px(8)) : p.moon ? Math.max(p.R + 4, px(10)) : p.R + 16)) return { kind: "planet", o: p };
    if (sc.sun && near(sc.sun, sc.sun.r + 8)) return { kind: "sun", o: sc.sun };
    for (const b of sc.subStates) if (near(b, Math.max(b.R, px(8)))) return { kind: "sat", o: b };
    for (const m of sc.moons) if (near(m, Math.max(m.R + 4, px(10)))) return { kind: "moon", o: m };
    for (const g of Object.values(sc.galaxies)) if (near(g, g.R)) return { kind: "galaxy", o: g };
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
  const pinnable = (s: Subject) => (s.kind === "task" ? level().kind === "board" || level().kind === "state" : level().kind === "machine");
  const goalOf = (m?: Machine) => m?.states.find((x) => x.final)?.name ?? "its end";
  /** A task's run, or why there is none yet. */
  function runFor(s: Subject): Run | "loading" | "unavailable" {
    if (s.kind === "task" && level().kind === "state") {
      const flow = scene!.hub?.name, rows = flow ? hist.machine(s.id, flow) : "unavailable";
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
        const o = h.o, at = subjectOf(h)!, kind = `task · ${stateName(o.state)}${o.host.states ? ` · orbiting ${(o.host as Planet).title || o.host.name}` : ""} · click ${pinnable(at) ? "to pin its path" : "for details"}`;
        return traceCard({ kind, id: o.id, title: o.title, goal: goalOf(sky.board.machine) }, runFor(at), prefs().clock);
      }
      case "mtask": {
        const o = h.o, at = subjectOf(h)!, kind = `task · ${o.flow} · ${o._state || o.state} · click ${pinnable(at) ? "to pin its path" : "for details"}`;
        return traceCard({ kind, id: o.id, title: "", goal: goalOf(sky.flows[o.flow]?.machine) }, runFor(at), prefs().clock);
      }
      case "dag": {
        const o = h.o, crit = (o.tether?.crit ?? []).map(esc).join("<br>");
        if (o.fold) return `<div class="k">${o.fold.length} DAGs on one ${o.tether?.edge ? "path" : "state"} · click to open them</div><div class="n">${o.fold.map(esc).join("<br>")}</div>${crit ? `<div class="k">${crit}</div>` : ""}`;
        const l = o.tether?.crit.some((t) => t.startsWith("launches ")) ? [] : sky.launches.filter((x) => x.dag === o.name && x.flow).map((x) => x.flow!);
        return `<div class="k">DAG · ${esc(o.group)} · ${esc(o.status)}${o.runnable ? " · runnable" : ""}</div><div class="n">${esc(o.name)}</div>${crit ? `<div class="k">${crit}</div>` : ""}${l.length ? `<div class="k">launches ${l.map(esc).join(", ")}</div>` : ""}${o.steps.length} step${o.steps.length === 1 ? "" : "s"}: ${o.steps.map((s) => esc(s.name)).join(" → ")}${o.finishedAt ? `<div class="k">last run ${hhmm(finished(o.finishedAt))} MST</div>` : ""}`;
      }
      case "hangar": {
        const run = h.o.names.filter((n) => sky.dagBy[n]?.status === "running");
        return `<div class="k">DAGs that write no Board lane · click to open</div><div class="n">DAGs</div>${h.o.names.length} DAGs in ${h.o.doms} domain${h.o.doms === 1 ? "" : "s"}${run.length ? `<div class="k">running: ${run.map(esc).join(", ")}</div>` : ""}`;
      }
      case "galaxy":
        return `<div class="k">Board state · click to open</div><div class="n">${esc(h.o.name)}</div>${h.o.n} tasks${h.o.subs.length ? ` · ${h.o.subs.length} lifecycle machines inside` : ""}`;
      case "moon": {
        const o = h.o, mv = moving(o.name).length, f = sky.flows[o.name];
        if (o.pager) return pagerTip(o.pager);
        return `<div class="k">lifecycle machine inside ${esc(o.parent.name)} · click to open it</div><div class="n">${esc(o.name)}</div>${o.nStates} states · ${f?.agents.length ?? 0} session${f?.agents.length === 1 ? "" : "s"}${mv ? ` · ${mv} moving now` : ""}`;
      }
      case "sat":
        return `<div class="k">state of the ${esc(h.o.machine)} machine · opens ${esc(h.o.flow)} ${esc(h.o.when)} · click to open ${esc(h.o.machine)}</div><div class="n">${esc(h.o.name)}</div>${h.o.n} task${h.o.n === 1 ? "" : "s"} orbiting`;
      case "sun":
        return `<div class="k">Board state</div><div class="n">${esc(h.o.name)}</div>${h.o.n} tasks${scene!.planets.length ? ` · ${scene!.planets.length} lifecycle machines orbiting it` : ""}`;
      case "state":
        return `<div class="k">${esc(h.o.flow)} state</div><div class="n">${esc(h.o.name)}</div>${h.o.n} task${h.o.n === 1 ? "" : "s"} here now${h.o.loops.length ? `<div class="k">stays here on ${h.o.loops.map(esc).join(", ")}</div>` : ""}`;
      case "planet": {
        const o = h.o, mv = moving(o.name).length;
        if (o.pager) return pagerTip(o.pager);
        if (o.subState) return `<div class="k">state of the ${esc(o.machine!)} machine · opens ${esc(o.flow!)} ${esc(o.when ?? "")} · click to open it</div><div class="n">${esc(o.title!)}</div>${o.n} task${o.n === 1 ? "" : "s"} here now`;
        return `<div class="k">lifecycle machine · click to open${o.when ? ` · ${esc(o.when)}` : ""}</div><div class="n">${esc(o.name)}</div>${Object.keys(o.states).length} states · ${o.n} task${o.n === 1 ? "" : "s"}${mv ? ` · ${mv} moving now` : ""}`;
      }
      case "link":
        return `<div class="k">machine path · ${esc(h.o.from)} → ${esc(h.o.to)}</div><div class="n">${h.o.back ? "the task returns from the skill" : "a task opens this skill"}</div>`;
      case "medge":
        return `<div class="k">${esc(h.o.flow)} transition · ${esc(h.o.source)} → ${esc(h.o.target)}</div><div class="n">${esc(h.o.event)}</div>`;
      case "bedge":
        return `<div class="k">Board transition${h.o.events.length > 1 ? `s (${h.o.events.length})` : ""} · ${esc(h.o.source)} → ${esc(h.o.target)}</div><div class="n">${h.o.events.map(esc).join("<br>")}</div>${h.o.writers.length ? h.o.writers.map(writerLine).join("<br>") : '<span class="k">no writer declared</span>'}`;
    }
  }

  // ---- click: drill into states, machines and DAGs, open panels for tasks ----
  // the panel floats over the level, so opening or closing it never moves or zooms the view
  const openPanel = () => {
    panel.classList.add("open");
    panel.querySelector<HTMLElement>(".x")!.onclick = () => closePanel();
  };
  /** Close the panel if one is open; whether one was. */
  function closePanel() {
    pin = null;
    if (!panel.classList.contains("open")) return false;
    panel.classList.remove("open");
    return true;
  }
  function openDagPanel(o: Dag & { group: string; runnable: boolean }) {
    const sky = S!, span = o.startedAt ? ` · ${hhmm(finished(o.startedAt))}–${o.finishedAt ? hhmm(finished(o.finishedAt)) : "…"} MST` : "";
    panel.innerHTML = `<span class="x">✕</span><div class="k">DAG · ${esc(o.group)}</div><h2>${esc(o.name)}</h2>
      <table><tr><td>Last run</td><td>${esc(o.status)}${o.raw ? ` (${esc(o.raw)})` : ""}${span}</td></tr>
      <tr><td>Steps</td><td>${o.steps.map((s) => `<span class="chip" style="color:${DAG_COLOR[s.status] || "#94a3b8"}">${esc(s.name)}</span>${s.depends.length ? `<span class="k"> after ${s.depends.map(esc).join(", ")}</span>` : ""}`).join("<br>")}</td></tr>
      <tr><td>Writes</td><td>${writes(o.name).map(esc).join(", ") || "no Board lane"}</td></tr>
      <tr><td>Launches</td><td>${sky.launches.filter((l) => l.dag === o.name).map((l) => esc(l.skill)).join(", ") || "no agent"}</td></tr>${cueLine(o.name) ? `
      <tr><td>Runs with</td><td>${cueLine(o.name)}</td></tr>` : ""}</table>
      <button class="run" ${o.runnable ? "" : "disabled"}>▶ Run now</button>
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
  function click(fx: number, fy: number) {
    const h = hover, sky = S;
    if (!h || !sky) return void closePanel();
    pin = null;
    if (h.kind === "galaxy") return push({ kind: "state", id: h.o.id }, fx, fy);
    if (h.kind === "moon" && h.o.pager) return changePage(h.o.pager);
    if (h.kind === "planet" && h.o.pager) return changePage(h.o.pager);
    if (h.kind === "planet") return push({ kind: "machine", flow: h.o.subState ? h.o.flow! : h.o.name }, fx, fy);
    // a moon opens its machine, and so does one of its sub-states (the machine the sub-state belongs to; its child opens from there)
    if (h.kind === "moon" || h.kind === "sat") return go([...path, { kind: "state", id: h.o.parent.id }, { kind: "machine", flow: h.kind === "moon" ? h.o.name : h.o.machine }], fx, fy);
    if (h.kind === "hangar") return push({ kind: "dags" }, fx, fy);
    // a fold drills into a level over the Board path its DAGs write; one DAG only opens its panel, on whatever level it is clicked
    if (h.kind === "dag") {
      const e = h.o.tether?.edge, d = drill(h.o, h.o.tether?.crit ?? [], e ? [e.source, e.target] : null);
      return "push" in d ? push(d.push, fx, fy) : openDagPanel(h.o);
    }
    const at = subjectOf(h);
    if (at && pinnable(at)) pin = at;
    if (h.kind === "task") panel.innerHTML = taskPanel(h.o, sky, stateName);
    else if (h.kind === "mtask") {
      const o = h.o;
      panel.innerHTML = `<span class="x">✕</span><div class="k">task · ${esc(o.flow)} · ${esc(o._state || o.state)}</div><h2>${esc(o.id)} — ${esc(o.title)}</h2>
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
  function text(s: string, x: number, y: number, size: number, col: string, align: CanvasTextAlign = "center", weight = 400) {
    cx.font = `${weight} ${size}px Inter, system-ui, sans-serif`;
    cx.fillStyle = col;
    cx.textAlign = align;
    cx.textBaseline = "middle";
    cx.fillText(s, x, y);
  }
  const labPx = (n: number) => labelPx(n, K, prefs().scale);
  // names sit outside their node in a light, translucent face (the same see-through weight as the flow lines); a hovered node's name firms up
  function label(name: string, x: number, y: number, hot: boolean, sub?: string | null, size = 12.5) {
    size = labelPx(size, K, prefs().scale); // type is a fixed size on screen: readable at fit, never balloons when zoomed in; the Admin font size scales it
    cx.letterSpacing = `${0.6 / K}px`;
    text(name, x, y, size, rgba("#cfd9ea", hot ? 0.95 : 0.58), "center", 300);
    if (sub) text(sub, x, y + size + 3 / K, size - labelPx(2, K, prefs().scale), rgba("#94a3b8", hot ? 0.8 : 0.42), "center", 300);
    cx.letterSpacing = "0px";
  }
  function circle(x: number, y: number, r: number, stroke: string, w = 1, dash?: number[] | null) {
    cx.strokeStyle = stroke;
    cx.lineWidth = w;
    cx.setLineDash(dash || []);
    cx.beginPath();
    cx.arc(x, y, r, 0, TAU);
    cx.stroke();
    cx.setLineDash([]);
  }
  function dot(x: number, y: number, r: number, fill: string) {
    cx.fillStyle = fill;
    cx.beginPath();
    cx.arc(x, y, r, 0, TAU);
    cx.fill();
  }
  const isHot = (kind: Hover["kind"], o: unknown) => !!hover && hover.kind === kind && hover.o === o;
  const hotDags = () => (hover?.kind === "dag" ? hover.o.fold ?? [hover.o.name] : []);
  const edgeLitBy = (e: BEdge) => {
    const d = hotDags();
    return e.writers.some((w) => d.includes(w.actor));
  };
  function disc(x: number, y: number, r: number, col: string, hot: boolean, alpha = 0.16) {
    const grd = cx.createRadialGradient(x, y, 0, x, y, r);
    grd.addColorStop(0, rgba(col, alpha));
    grd.addColorStop(1, rgba(col, 0.02));
    cx.fillStyle = grd;
    cx.beginPath();
    cx.arc(x, y, r, 0, TAU);
    cx.fill();
    circle(x, y, r, rgba(col, hot ? 0.9 : 0.4), hot ? 2 : 1.2);
  }
  /** A terminal state as a black hole: a lensing halo in the state's colour, a shadow darker than the sky, one bright photon ring and a faint outer edge. */
  function hole(x: number, y: number, r: number, col: string, hot: boolean) {
    const rs = r * 0.6, g = cx.createRadialGradient(x, y, rs, x, y, r);
    g.addColorStop(0, rgba(col, hot ? 0.42 : 0.28));
    g.addColorStop(1, rgba(col, 0));
    cx.fillStyle = g;
    cx.beginPath();
    cx.arc(x, y, r, 0, TAU);
    cx.fill();
    dot(x, y, rs, "#010205");
    circle(x, y, rs, rgba(col, hot ? 1 : 0.85), hot ? 2 : 1.4);
    circle(x, y, r, rgba(col, hot ? 0.5 : 0.14), 1);
  }
  /** The value `key` shows on this level, eased from the one it showed when a snapshot changes it: the Board's places, sky and sizes and a
   *  state's sun take it as the level is laid out (`layout`), so their tasks, paths and neighbours move with them; a machine's states draw at it. */
  const sized = (key: string, r: number) => grown.of(`${pathKey(path)}|${key}`, r, performance.now());
  /** A Board state's or a fold end's body: a black hole where a task's lifecycle ends, else its disc. */
  const body = (o: Pt & { id: string; name: string; r: number; color: string; final: boolean }, hot: boolean) => {
    if (terminal(o)) hole(o.x, o.y, o.r, o.color, hot);
    else disc(o.x, o.y, o.r, o.color, hot);
  };
  // the current board's hop: a tapering tail (alpha and width grow toward the head), then a glowing head, in the mover's model colour
  function comet(p0: Pt, c: Pt, p1: Pt, u: number, r = 3, col = ACT) {
    const n = 14, span = 0.27 * Math.min(1, u + 0.05);
    for (let i = 1; i <= n; i++) {
      const a = bez(p0, c, p1, Math.max(0, u - span * (1 - (i - 1) / n))), b = bez(p0, c, p1, Math.max(0, u - span * (1 - i / n)));
      cx.strokeStyle = rgba(col, (i / n) * 0.6);
      cx.lineWidth = ((i / n) * 2.6) / Math.max(1, ZS * 0.8);
      cx.beginPath();
      cx.moveTo(a.x, a.y);
      cx.lineTo(b.x, b.y);
      cx.stroke();
    }
    const h = bez(p0, c, p1, u), gr = 14 / ZS;
    cx.globalCompositeOperation = "lighter";
    const g = cx.createRadialGradient(h.x, h.y, 0, h.x, h.y, gr);
    g.addColorStop(0, rgba(col, 0.7));
    g.addColorStop(1, rgba(col, 0));
    cx.fillStyle = g;
    cx.beginPath();
    cx.arc(h.x, h.y, gr, 0, TAU);
    cx.fill();
    cx.globalCompositeOperation = "source-over";
    dot(h.x, h.y, r, rgba(col, 0.95));
  }
  // an arrival's ring: one ring, radius eased out, fading fast; sized in screen terms so a hard zoom keeps it small
  function pulse(x: number, y: number, r: number, age: number, col = ACT, grow = 38) {
    for (const q of arrivalRings(age)) {
      circle(x, y, r + (easeO(q) * grow) / ZS, rgba(col, Math.pow(1 - q, 2) * 0.85), (2 * (1 - q) + 0.4) / ZS);
    }
  }
  const drawTrackRings = (host: { x: number; y: number; rings?: number[] }, col: string) => {
    for (const R of host.rings || []) circle(host.x, host.y, R, rgba(col, 0.11));
  };
  // a lifecycle machine is a flat disc with a thin ring outside it, the one mark that tells it from a state
  function machine(x: number, y: number, r: number, hot: boolean, alpha: number) {
    disc(x, y, r, "#c084fc", hot, alpha);
    circle(x, y, r + 3, rgba("#c084fc", hot ? 0.9 : 0.5), 1);
  }

  function drawGalaxies() {
    for (const g of Object.values(scene!.galaxies)) {
      const hot = isHot("galaxy", g);
      body(g, hot);
      drawTrackRings(g, g.color);
      label(g.name, g.lab.x, g.lab.y, hot, `${g.n}${g.subs.length ? ` · ${g.subs.length} lifecycles` : ""}`, 13);
    }
  }
  // lifecycle moons: still, named bodies on their state's dashed outer ring, brighter while they have sessions, ringed in amber while one moves.
  // A machine's sub-states run outward from its moon in its row on dashed stems, the machine's name past them.
  function drawMoons() {
    const sc = scene!;
    for (const g of Object.values(sc.galaxies)) if (sc.moons.some((m) => m.parent === g)) circle(g.x, g.y, g.moonR, rgba(g.color, isHot("galaxy", g) ? 0.6 : 0.25), 1, [2, 5]);
    for (const m of sc.moons) {
      const hot = isHot("moon", m), flows = m.pager?.hidden ?? [m.name], mv = flows.flatMap(moving).length, busy = flows.some((name) => !!S!.flows[name]?.agents.length);
      drawTrackRings(m, "#c084fc");
      machine(m.x, m.y, m.r!, hot, busy ? 0.32 : 0.14);
      if (mv) circle(m.x, m.y, m.r! + 4, rgba(ACT, 0.85), 1.5);
      // named beside the moon on the side away from its state, past its chain of sub-states
      const left = m.x < m.parent.x - 1;
      cx.letterSpacing = `${0.5 / K}px`;
      const col = rgba("#d8c8f5", hot ? 0.95 : 0.6);
      text(sc.clipped ? clip(m.label) : m.label, m.x + (left ? -1 : 1) * (m.R + m.ext + 10), m.y, labPx(10.5), col, left ? "right" : "left", 300);
      cx.letterSpacing = "0px";
    }
    for (const b of sc.subStates) {
      const hot = isHot("sat", b), u = Math.sign(b.x - b.prev.x) || 1, col = b.color!;
      cx.strokeStyle = rgba(col, hot ? 0.75 : 0.4);
      cx.lineWidth = 1 / K ** 0.5;
      cx.setLineDash([2 / K, 3 / K]);
      cx.beginPath();
      cx.moveTo(b.prev.x + u * ((b.prev.r ?? b.prev.R) + 3), b.prev.y);
      cx.lineTo(b.x - u * (b.r! + 3), b.y);
      cx.stroke();
      cx.setLineDash([]);
      disc(b.x, b.y, b.r!, col, hot, 0.22);
      drawTrackRings(b, col);
    }
  }
  function drawSun() {
    const s = scene!.sun;
    if (!s) return;
    const hot = isHot("sun", s), r = s.r;
    // a terminal state's level centres on the black hole the Board draws for it, at the same size
    if (terminal(s)) {
      hole(s.x, s.y, r, s.color, hot);
      drawTrackRings(s, s.color);
      return;
    }
    // the glow reaches as far past the sun as it did when every sun was GALAXY_MIN, so a large sun does not wash out its level
    const glow = cx.createRadialGradient(s.x, s.y, 0, s.x, s.y, r + 5 * GALAXY_MIN);
    glow.addColorStop(0, rgba(s.color, 0.55));
    glow.addColorStop(0.25, rgba(s.color, 0.2));
    glow.addColorStop(1, rgba(s.color, 0));
    cx.fillStyle = glow;
    cx.beginPath();
    cx.arc(s.x, s.y, r + 5 * GALAXY_MIN, 0, TAU);
    cx.fill();
    const core = cx.createRadialGradient(s.x, s.y, 0, s.x, s.y, r);
    core.addColorStop(0, "#f5f3ff");
    core.addColorStop(0.5, rgba(s.color, 0.95));
    core.addColorStop(1, rgba(s.color, 0.6));
    cx.fillStyle = core;
    cx.beginPath();
    cx.arc(s.x, s.y, r * (1 + 0.04 * Math.sin(clock * 2)), 0, TAU);
    cx.fill();
    if (hot) circle(s.x, s.y, r + 5, rgba(s.color, 0.9), 1.5);
    drawTrackRings(s, s.color);
  }
  // action lines as on the current board: a dashed stroke that streams toward its target, a gradient from source colour to target colour,
  // brighter and thicker while a writer DAG has just run (or is running)
  const dagHeat = (n: string) => {
    const d = S!.dagBy[n];
    if (!d) return 0;
    if (d.status === "running") return 1;
    const f = moves.flare[n];
    return f !== undefined && f <= T ? Math.max(0, 1 - (T - f) / FLARE) : 0;
  };
  function flowLine(a: Pt & { color: string }, b: Pt & { color: string }, alpha: number, heat: number, dash = [2, 5]) {
    const g = cx.createLinearGradient(a.x, a.y, b.x, b.y);
    g.addColorStop(0, rgba(a.color, alpha));
    g.addColorStop(1, rgba(b.color, alpha));
    cx.strokeStyle = g;
    cx.lineWidth = (1 + heat * 1.5) / Math.min(1, K) ** 0.5 / Math.max(1, ZS);
    cx.setLineDash(dash.map((d) => (d / K) * 1.2));
    cx.lineDashOffset = ((-clock * 12) / K) * 1.2;
  }
  function drawBoardEdges() {
    const sc = scene!;
    for (const e of sc.bEdges) {
      const lit = isHot("bedge", e) || edgeLitBy(e), col = sc.galaxies[e.source].color, heat = Math.max(hotEdge.has(`board:${e.source}>${e.target}`) ? 1 : 0, ...e.writers.map((w) => dagHeat(w.actor)));
      flowLine({ ...e.p0!, color: col }, { ...e.p1!, color: sc.galaxies[e.target].color }, lit ? 0.95 : (e.events.every((v) => v === "ARCHIVE") ? 0.1 : 0.2) + heat * 0.55, heat + (lit ? 0.8 : 0));
      cx.beginPath();
      cx.moveTo(e.p0!.x, e.p0!.y);
      cx.quadraticCurveTo(e.c!.x, e.c!.y, e.p1!.x, e.p1!.y);
      cx.stroke();
      cx.setLineDash([]);
    }
  }
  // state level: the paths between machines and the Board paths off the edges, drawn as the Board draws its transitions
  function drawStateLinks() {
    const sc = scene!, stroke = (l: Curve) => {
      cx.beginPath();
      cx.moveTo(l.p0.x, l.p0.y);
      cx.quadraticCurveTo(l.c.x, l.c.y, l.p1.x, l.p1.y);
      cx.stroke();
      cx.setLineDash([]);
    };
    for (const l of sc.hops) {
      const lit = isHot("link", l), heat = l.busy ? 1 : 0;
      flowLine({ ...l.p0, color: "#a78bfa" }, { ...l.p1, color: "#c084fc" }, lit ? 0.95 : 0.22 + heat * 0.55, heat + (lit ? 0.8 : 0));
      stroke(l);
    }
    for (const l of [...sc.entries, ...sc.exits]) {
      if (!l.p0) continue;
      const lit = isHot("bedge", l) || edgeLitBy(l), heat = Math.max(l.busy ? 1 : 0, ...l.writers.map((w) => dagHeat(w.actor)));
      flowLine({ ...l.p0, color: BOARD_COLOR[l.source] ?? "#94a3b8" }, { ...l.p1!, color: BOARD_COLOR[l.target] ?? "#94a3b8" }, lit ? 0.95 : (l.events.every((v) => v === "ARCHIVE") ? 0.1 : 0.2) + heat * 0.55, heat + (lit ? 0.8 : 0));
      stroke(l as Curve);
      label(l.lab!.name, l.lab!.x, l.lab!.y - 12 / K, lit, null, 10.5);
    }
  }
  function drawMachineEdges(edges: MEdge[], thin = false) {
    for (const e of edges) {
      if (!e.a || !e.b) continue;
      const lit = isHot("medge", e), heat = hotEdge.has(`${e.flow}:${e.source}>${e.target}`) ? 1 : 0;
      if (e.a === e.b) continue; // a self-transition would sit under the orbiting tasks, so the state's tooltip lists it
      const c = curveOf(e.a, e.b), L = Math.hypot(e.b.x - e.a.x, e.b.y - e.a.y), t0 = Math.min(0.4, stateR(e.a) / L), tEnd = 1 - Math.min(0.4, (stateR(e.b) + 2) / L);
      flowLine(e.a, e.b, lit ? 0.95 : 0.2 + heat * 0.55, heat + (lit ? 0.8 : 0), thin ? [1.5, 4] : [2, 5]);
      cx.beginPath();
      for (let i = 0; i <= 16; i++) {
        const p = bez(c.p0, c.c, c.p1, t0 + ((tEnd - t0) * i) / 16);
        if (i) cx.lineTo(p.x, p.y);
        else cx.moveTo(p.x, p.y);
      }
      cx.stroke();
      cx.setLineDash([]);
    }
  }
  function drawStates(states: Record<string, MState>, labels: boolean) {
    for (const s of Object.values(states)) {
      const R = sized(`state|${s.flow}:${s.id}`, stateR(s)), hot = isHot("state", s);
      if (terminal(s)) {
        hole(s.x, s.y, R, s.color, hot);
        if (labels) label(s.name, s.lab ? s.lab.x : s.x, s.lab ? s.lab.y : s.y + R + 16, hot);
        continue;
      }
      dot(s.x, s.y, R, "rgba(6,10,20,0.9)");
      circle(s.x, s.y, R, rgba(s.color, hot ? 1 : s.n ? 0.85 : 0.45), hot ? 2.2 : s.mini ? 1 : 1.6);
      dot(s.x, s.y, s.mini ? 1.5 : s.initial ? 4 : 2.5, rgba(s.color, 0.9));
      if (labels) label(s.name, s.lab ? s.lab.x : s.x, s.lab ? s.lab.y : s.y + R + 16, hot);
    }
  }
  // machine level: each task sits on the state its latest machine event left it in; a move the page has just seen slides it along its edge as a comet
  function drawMachineTasks() {
    const sc = scene!, at: Record<string, number> = {};
    for (const s of sc.machineTasks) {
      s._x = undefined;
      const ev = EVENTS().findLast((e) => e.task === s.id && e.flow === s.flow && e.at <= T), state = ev ? ev.to : s.state;
      const cur = sc.mStates[state];
      if (!cur) continue;
      s._state = state;
      const prev = ev?.from ? sc.mStates[ev.from] : null, u = ev ? (T - ev.at) / TRAVEL : 9;
      if (prev && prev !== cur && u < 1) {
        const c = curveOf(prev, cur), q = bez(c.p0, c.c, c.p1, easeO(u));
        comet(c.p0, c.c, c.p1, easeO(u), 3.4, tierColor(s.model));
        s._x = q.x;
        s._y = q.y;
        continue;
      }
      const pa = ev ? (T - ev.at - TRAVEL) / PULSE : 9;
      if (prev && prev !== cur && pa >= 0 && pa < 1) pulse(cur.x, cur.y, stateR(cur), pa, cur.color); // the state it landed on rings once
      const k = (at[state] = (at[state] || 0) + 1) - 1, { t, rr } = taskSlot(sized(`state|${cur.flow}:${cur.id}`, stateR(cur)) + 7, k);
      s._x = cur.x + Math.cos(t) * rr;
      s._y = cur.y + Math.sin(t) * rr;
      const hot = isHot("mtask", s), r = hot ? 4.5 : 2.8;
      cx.fillStyle = rgba(tierColor(s.model), 0.9);
      cx.beginPath();
      cx.arc(s._x, s._y, r, 0, TAU);
      cx.fill();
    }
  }
  function drawTasks() {
    for (const t of scene!.tasks) {
      if (t.gone) continue;
      const hot = isHot("task", t), r = t.big ? 4.2 : 2.6, lit = liveTasks.has(t.id);
      if (t.arrive) pulse(t.arrive.x, t.arrive.y, t.arrive.r || 10, t.arrive.age, t.arrive.col);
      if (t.moving && t.hop) {
        const c = t.hop.c;
        comet(c.p0, c.c, c.p1, t.hop.u, 3.2, tierColor(t.model)); // the head is drawn by the comet
        if (t.via) {
          const h = bez(c.p0, c.c, c.p1, t.hop.u);
          label(`${t.id} ${t.via}`, h.x, h.y - 16 / K, false, null, 10.5);
        }
        continue;
      }
      if (t.big)
        for (let i = 0; i < 8; i++) {
          const a0 = t.ang - Math.sign(t.w) * 0.05 * (i + 1), a1 = t.ang - Math.sign(t.w) * 0.05 * i;
          cx.strokeStyle = rgba(tierColor(t.model), 0.34 * (1 - i / 8));
          cx.lineWidth = 2.2 * (1 - i / 10);
          cx.beginPath();
          cx.arc(t.host.x, t.host.y, t.R, Math.min(a0, a1), Math.max(a0, a1));
          cx.stroke();
        }
      dot(t.x, t.y, hot ? r * 1.7 : r, rgba(tierColor(t.model), hot || lit ? 1 : 0.8));
    }
  }
  // state level: each planet runs its own machine; every move is a comet along its chord and the planet's rim glows while it moves
  // what sits beside a moon (its DAGs, its name) clears its orbits and its ring; `past` is where its launch-only DAGs start, beyond its sub-states
  const clear = (p: Planet) => Math.max(p.rim ?? p.R, p.R + 5), past = (p: Planet) => clear(p) + (p.ext ?? 0) + 16;
  // the dashed stem from a moon (or the sub-state before it) out to a sub-state, edge to edge
  function stem(a: Planet, b: Planet, col: string, hot: boolean) {
    const u = Math.sign(b.x - a.x) || 1;
    cx.strokeStyle = rgba(col, hot ? 0.75 : 0.4);
    cx.lineWidth = 1 / K ** 0.5;
    cx.setLineDash([2 / K, 3 / K]);
    cx.beginPath();
    cx.moveTo(a.x + u * (a.R + 3), a.y);
    cx.lineTo(b.x - u * (b.R + 3), b.y);
    cx.stroke();
    cx.setLineDash([]);
  }
  function drawPlanets() {
    const sc = scene!;
    for (const p of sc.planets) {
      const hot = isHot("planet", p), mv = p.pager ? p.pager.hidden.flatMap(moving) : moving(p.name);
      if (p.anchor) {
        cx.strokeStyle = rgba("#a78bfa", 0.4);
        cx.setLineDash([2, 4]);
        cx.lineWidth = 1;
        cx.beginPath();
        cx.moveTo(p.anchor.x, p.anchor.y + stateR(p.anchor) + 26);
        cx.lineTo(p.x, p.y - p.R - 18);
        cx.stroke();
        cx.setLineDash([]);
      }
      for (const R of p.rings || []) circle(p.x, p.y, R, rgba("#c4b5fd", 0.26), 1, [1.5, 4]); // the task orbits around this machine
      // a sub-state: a small fuchsia disc on a dashed stem from the body before it
      if (p.subState) {
        stem(p.prev!, p, "#e879f9", hot);
        disc(p.x, p.y, p.R, "#e879f9", hot, p.n ? 0.32 : 0.22);
        continue;
      }
      // a skill moon: a still disc, brighter while it has sessions and ringed in amber while one moves, named beside it away from the primary, past
      // the DAGs that orbit it; hover adds its states and sessions
      if (p.moon) {
        const sd = p.x < sc.hub!.x ? -1 : 1;
        machine(p.x, p.y, p.R, hot, p.n ? 0.32 : 0.14);
        if (mv.length) circle(p.x, p.y, p.R + 4, rgba(ACT, 0.85), 1.5);
        cx.letterSpacing = `${0.5 / K}px`;
        const col = rgba("#d8c8f5", hot ? 0.95 : 0.6);
        text(p.label || p.name, p.x + sd * (past(p) + (p.owned ?? 0) * OWNED), p.y, labPx(11.5), col, sd < 0 ? "right" : "left", 300);
        cx.letterSpacing = "0px";
        continue;
      }
      dot(p.x, p.y, p.R + 14, "rgba(10,14,26,0.85)");
      if (mv.length) {
        const g = cx.createRadialGradient(p.x, p.y, p.R + 14, p.x, p.y, p.R + 30);
        g.addColorStop(0, rgba(ACT, 0.2));
        g.addColorStop(1, rgba(ACT, 0));
        cx.fillStyle = g;
        cx.beginPath();
        cx.arc(p.x, p.y, p.R + 30, 0, TAU);
        cx.arc(p.x, p.y, p.R + 14, 0, TAU, true);
        cx.fill();
      }
      circle(p.x, p.y, p.R + 14, mv.length ? rgba(ACT, 0.6) : rgba("#c084fc", hot ? 0.9 : p.n ? 0.45 : 0.22), hot ? 2 : 1.2);
      drawMachineEdges(p.edges, true);
      drawStates(p.states, false);
      for (const e of mv) {
        const a = e.from ? p.states[e.from] : undefined, b = p.states[e.to];
        if (!a || !b || a === b) continue;
        const c = curveOf(a, b);
        comet(c.p0, c.c, c.p1, easeO((T - e.at) / TRAVEL), p.primary ? 3 : 2.4);
      }
      // a skill machine's name sits on its side facing away from the primary, so it never crosses the paths between them; the primary's goes below
      const nt = sc.tasks.filter((k) => k.host === p && !k.gone).length, size = p.primary ? 14 : 12;
      const sub = `${Object.keys(p.states).length} states${nt ? ` · ${nt} task${nt === 1 ? "" : "s"} orbiting` : ""} · ${p.n} task${p.n === 1 ? "" : "s"}${mv.length ? ` · ${mv.length} moving` : ""}`;
      let ux = 0, uy = 1;
      const hub = sc.hub;
      if (hub && p !== hub) {
        const dx = p.x - hub.x, dy = p.y - hub.y, L = Math.hypot(dx, dy) || 1;
        [ux, uy] = [dx / L, dy / L];
      }
      const off = Math.max(p.outer || 0, p.R + 14) + 20, hw = Math.max(textW(p.name, size), textW(sub, size - 2)) / 2;
      label(p.name, p.x + ux * (off + Math.abs(ux) * hw * 1.05), p.y + uy * off + (uy < 0 ? -16 : 0), hot, sub, size);
    }
  }
  // DAGs that launch only one skill machine sit beside it as small dots in their status colour, past its name; hover names them
  function drawOwned() {
    for (const s of Object.values(scene!.stars)) {
      if (!s.owned) continue;
      const hot = isHot("dag", s), col = DAG_COLOR[s.status] || "#94a3b8", fin = s.finishedAt ? finished(s.finishedAt) : 0;
      dot(s.x, s.y, 4.2, "rgba(6,10,20,0.9)");
      circle(s.x, s.y, 4.2, rgba(col, hot ? 1 : 0.8), hot ? 1.5 : 1);
      dot(s.x, s.y, 1.6, rgba(col, 0.9));
      if (s.status === "running" || (fin && fin <= T && T - fin < PULSE)) pulse(s.x, s.y, 5, s.status === "running" ? (clock % 2) / 2 : (T - fin) / PULSE, ACT, 18);
      if (hot) label(s.name, s.x, s.y - 16 / K, true, null, 11);
    }
  }
  // the one tether a hovered Board DAG draws, to the middle of the path most of its criteria sit on (or the rim of its state's galaxy); a fold's runs are its members'
  function drawTethers() {
    for (const [s, a] of tethersDrawn(scene!, draws(hover, pin).dag)) {
      const heat = Math.max(...(s.fold ?? [s.name]).map(dagHeat)), L = a.g ? Math.hypot(s.x - a.g.x, s.y - a.g.y) || 1 : 1;
      const tx = a.g ? a.g.x + ((s.x - a.g.x) / L) * a.g.R : a.x, ty = a.g ? a.g.y + ((s.y - a.g.y) / L) * a.g.R : a.y;
      const lo = a.cue ? 0.5 : 1; // a cue is a looser tie than a write: half as bright, sparser dots
      cx.strokeStyle = rgba("#fbbf24", (0.85 + heat * 0.15) * lo);
      cx.lineWidth = 1.3 / K ** 0.5;
      cx.setLineDash(a.cue ? [1.5 / K, 8 / K] : [2 / K, 5 / K]);
      cx.lineDashOffset = (-clock * 8) / K;
      cx.beginPath();
      cx.moveTo(s.x, s.y);
      cx.lineTo(tx, ty);
      cx.stroke();
      cx.setLineDash([]);
      if (!a.g) dot(tx, ty, 2.2 / K ** 0.5, rgba("#fbbf24", 0.8));
    }
  }
  function drawHangar() {
    const h = scene!.hangar;
    if (!h) return;
    const hot = isHot("hangar", h), heat = Math.max(0, ...h.names.map(dagHeat)), col = "#5eead4";
    disc(h.x, h.y, h.r, col, hot || heat > 0.5, 0.12 + heat * 0.25);
    h.names.forEach((n, i) => {
      const a = (i / h.names.length) * TAU - Math.PI / 2;
      dot(h.x + Math.cos(a) * (h.r + 9), h.y + Math.sin(a) * (h.r + 9), 1.8, rgba(DAG_COLOR[S?.dagBy[n]?.status ?? ""] || "#94a3b8", 0.35 + 0.6 * dagHeat(n)));
    });
    label("DAGs", h.x, h.y + h.r + 30, hot, `${h.names.length} · ${h.doms} domain${h.doms === 1 ? "" : "s"}`, 12.5);
  }
  function drawStars() {
    if (scene!.fold) drawFoldTies();
    else drawTethers();
    for (const grp of scene!.groups) {
      if (grp.head !== false) label(grp.name.toUpperCase(), grp.lx, grp.ly, false, null, 10.5);
      for (const s of grp.stars) {
        const col = DAG_COLOR[s.status] || "#94a3b8", hot = isHot("dag", s), g = s.glyph;
        if (hot || s.status === "running") {
          // no resting glow: only a hovered or currently running DAG gets a faint halo
          const glow = cx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.br * 1.3);
          glow.addColorStop(0, rgba(col, 0.09));
          glow.addColorStop(1, rgba(col, 0));
          cx.fillStyle = glow;
          cx.beginPath();
          cx.arc(s.x, s.y, s.br * 1.3, 0, TAU);
          cx.fill();
        }
        label(s.label, s.x, s.y + g.h / 2 + 16 / K, hot, null, 11);
        // the DAG's own step graph in miniature: rounded links streaming toward the step that waits, ringed steps
        const nr = (g.nodes.length === 1 ? 5.5 : 4) * (hot ? 1.15 : 1);
        for (const [p, q] of g.links) {
          const a = { x: s.x + p.x, y: s.y + p.y, color: DAG_COLOR[p.status] || "#94a3b8" }, b = { x: s.x + q.x, y: s.y + q.y, color: DAG_COLOR[q.status] || "#94a3b8" };
          const running = p.status === "running" || q.status === "running", dx = (b.x - a.x) / 2;
          flowLine(a, b, hot || running ? 0.8 : 0.42, running ? 0.6 : 0, [1.5, 3.5]);
          cx.beginPath();
          cx.moveTo(a.x + nr, a.y);
          cx.bezierCurveTo(a.x + dx, a.y, b.x - dx, b.y, b.x - nr, b.y);
          cx.stroke();
          cx.setLineDash([]);
        }
        for (const n of g.nodes) {
          const c = DAG_COLOR[n.status] || col, idle = n.status === "not_started", x = s.x + n.x, y = s.y + n.y;
          dot(x, y, nr, "rgba(6,10,20,0.9)");
          circle(x, y, nr, rgba(c, hot ? 1 : idle ? 0.45 : 0.85), hot ? 1.4 : 1);
          dot(x, y, nr * 0.34, rgba(c, idle ? 0.45 : 0.9));
        }
        if (s.runnable) circle(s.x, s.y, s.br, rgba("#dbe4f3", 0.35), 1, [2, 3]);
        for (const n of s.fold ?? [s.name]) for (const age of dagRings(moves.flare[n], T)) pulse(s.x, s.y, s.br, age, ACT, 38); // each run ending rings its DAG
      }
    }
  }
  // a fold's level: every DAG's ties to the events it writes or runs beside stay drawn, brighter on the hovered DAG; a cue is fainter and sparser
  function drawFoldTies() {
    for (const t of scene!.fold!.ties) {
      const s = scene!.stars[t.dag], hot = isHot("dag", s), lo = t.cue ? 0.5 : 1;
      cx.strokeStyle = rgba("#fbbf24", (hot ? 0.85 : 0.45) * lo);
      cx.lineWidth = (hot ? 1.3 : 1) / K ** 0.5;
      cx.setLineDash(t.cue ? [1.5 / K, 8 / K] : [2 / K, 5 / K]);
      cx.lineDashOffset = (-clock * 8) / K;
      cx.beginPath();
      cx.moveTo(s.x, s.y);
      cx.lineTo(t.x, t.y);
      cx.stroke();
      cx.setLineDash([]);
      dot(t.x, t.y, 2.2 / K ** 0.5, rgba("#fbbf24", hot ? 0.8 : 0.3));
    }
  }
  // a fold's level: the Board path its DAGs write, from one state's disc to the other's, with the events they tie to marked on it
  function drawFold() {
    const f = scene!.fold;
    if (!f?.a || !f.b || !f.p0 || !f.p1) return;
    const hot = hover?.kind === "dag" ? hover.o : null, lit = !!hot, heat = Math.max(hotEdge.has(`board:${f.a.id}>${f.b.id}`) ? 1 : 0, ...scene!.groups.flatMap((g) => g.stars).map((s) => dagHeat(s.name)));
    flowLine({ ...f.p0, color: f.a.color }, { ...f.p1, color: f.b.color }, (lit ? 0.75 : 0.4) + heat * 0.4, heat + (lit ? 0.5 : 0));
    cx.beginPath();
    cx.moveTo(f.p0.x, f.p0.y);
    cx.lineTo(f.p1.x, f.p1.y);
    cx.stroke();
    cx.setLineDash([]);
    const L = 7 / Math.max(1, ZS);
    cx.fillStyle = rgba(f.b.color, 0.6);
    cx.beginPath();
    cx.moveTo(f.p1.x, f.p1.y);
    cx.lineTo(f.p1.x - L * Math.cos(-0.4), f.p1.y - L * Math.sin(-0.4));
    cx.lineTo(f.p1.x - L * Math.cos(0.4), f.p1.y - L * Math.sin(0.4));
    cx.fill();
    for (const e of [f.a, f.b]) {
      body(e, false);
      label(e.name, e.x, e.y + e.r + 24 / K, false, null, 13);
    }
    for (const e of f.events) {
      const on = !!hot && f.ties.some((t) => t.dag === hot.name && t.ev === e.name), r = 4 / K ** 0.5;
      dot(e.x, e.y, r, "rgba(6,10,20,0.95)");
      circle(e.x, e.y, r, rgba("#fbbf24", on ? 1 : 0.6), 1.2 / K ** 0.5);
      label(e.name, e.x, e.y + 22 / K, on, null, 11);
    }
  }
  const TRACE = "#fbbf24", OFF = "#fb7185";
  function arrow(from: Pt, to: Pt, col: string, size: number) {
    const a = Math.atan2(to.y - from.y, to.x - from.x), s = size / K;
    cx.fillStyle = col;
    cx.beginPath();
    cx.moveTo(to.x, to.y);
    cx.lineTo(to.x - s * Math.cos(a - 0.4), to.y - s * Math.sin(a - 0.4));
    cx.lineTo(to.x - s * Math.cos(a + 0.4), to.y - s * Math.sin(a + 0.4));
    cx.closePath();
    cx.fill();
  }
  function badge(p: Pt, nums: number[], col: string) {
    const s = nums.join(" · "), w = Math.max(16 / K, textW(s, 10.5) / K + 10 / K), h = 16 / K;
    cx.fillStyle = "rgba(6,10,20,0.96)";
    cx.strokeStyle = rgba(col, 0.95);
    cx.lineWidth = 1.2 / K;
    cx.beginPath();
    cx.roundRect(p.x - w / 2, p.y - h / 2, w, h, h / 2);
    cx.fill();
    cx.stroke();
    text(s, p.x, p.y + 0.5 / K, 10.5 / K, "#fef3c7", "center", 600);
  }
  function pill(s: string, x: number, y: number, col: string) {
    const w = textW(s, 10.5) / K + 12 / K, h = 17 / K;
    cx.fillStyle = "rgba(6,10,20,0.92)";
    cx.strokeStyle = rgba(col, 0.6);
    cx.lineWidth = 1 / K;
    cx.beginPath();
    cx.roundRect(x - w / 2, y - h / 2, w, h, 4 / K);
    cx.fill();
    cx.stroke();
    text(s, x, y + 0.5 / K, 10.5 / K, "#f8fafc", "center", 500);
  }
  /** Where the traced task sits now, or null when this level does not draw it. */
  function bodyOf(s: Subject): (Pt & { model: string }) | null {
    const sc = scene!;
    if (s.kind === "task") return sc.tasks.find((t) => t.id === s.id && !t.gone) ?? null;
    const m = sc.machineTasks.find((t) => t.id === s.id && t.flow === s.flow);
    return m && m._x !== undefined ? { x: m._x, y: m._y!, model: m.model } : null;
  }
  type Mode = "board" | "state" | "machine";
  /** A state level's body by the name its trail gives it, and the name a trace shows for it. */
  // a trail host is a body's name, or `primary#state` for a state of the primary
  const planetOf = (name: string) => scene!.planets.find((p) => p.name === name.split("#")[0]);
  const planetName = (name: string) => {
    const p = planetOf(name), st = name.includes("#") ? p?.states[name.split("#")[1]] : undefined;
    return st ? st.name : p ? p.title || p.label || p.name : name;
  };
  const placesOf = (mode: Mode): Record<string, Place> => {
    const sc = scene!;
    // a state level's bodies: the primary's rim is its dark halo, a moon's or sub-state's its disc
    if (mode === "state") return Object.fromEntries(sc.planets.flatMap((p) => {
      const r = p.moon || p.subState ? p.R : p.R + 14, states = p.primary ? Object.values(p.states) : [];
      return [
        [p.name, { id: p.name, name: planetName(p.name), x: p.x, y: p.y, r, R: r + 12 / K, color: p.subState ? "#e879f9" : p.moon ? "#c4b5fd" : "#c084fc", lab: { x: p.x, y: p.y + r + 16 / K } }],
        ...states.map((m) => {
          const id = `${p.name}#${m.id}`, mr = stateR(m);
          return [id, { id, name: m.name, x: m.x, y: m.y, r: mr, R: mr + 8 / K, color: m.color, lab: m.lab ?? { x: m.x, y: m.y + mr + 12 } }];
        }),
      ];
    }));
    if (mode === "board") return Object.fromEntries(Object.values(sc.galaxies).map((g) => [g.id, { id: g.id, name: g.name, x: g.x, y: g.y, r: g.r, R: g.R, color: g.color, lab: g.lab }]));
    return Object.fromEntries(Object.values(sc.mStates).map((m) => {
      const r = stateR(m);
      return [m.id, { id: m.id, name: m.name, x: m.x, y: m.y, r, R: r + 12 / K, color: m.color, lab: m.lab ?? { x: m.x, y: m.y + r + 16 } }];
    }));
  };
  const edgeOf = (mode: Mode) => (from: string, to: string): Curve | null => {
    const sc = scene!;
    if (mode === "state") {
      // inside the primary, its machine's path; between bodies, the hop the level draws
      const [fa, fs] = from.split("#"), [ta, ts] = to.split("#");
      if (fs && ts) {
        const e = planetOf(from)?.edges.find((q) => q.a && q.b && q.source === fs && q.target === ts);
        return e ? curveOf(e.a!, e.b!) : null;
      }
      const h = sc.hops.find((q) => q.from === fa && q.to === ta);
      return h ? { p0: h.p0, c: h.c, p1: h.p1 } : null;
    }
    if (mode === "board") {
      const e = sc.bEdges.find((q) => q.p0 && q.source === from && q.target === to);
      return e ? { p0: e.p0!, c: e.c!, p1: e.p1! } : null;
    }
    const e = sc.mEdges.find((q) => q.a && q.b && q.source === from && q.target === to);
    return e ? curveOf(e.a!, e.b!) : null;
  };
  // A hovered task lights the path it took through this level, in order; a pinned one is the focused setting, and everything else steps back
  // under a dark veil from the click itself. A state level lights the bodies (primary, moons, sub-states) the task's session moved through.
  function drawTrace() {
    const t = draws(hover, pin).trace, sc = scene!;
    if (!t || !S || !pinnable(t.subject)) return;
    const body = bodyOf(t.subject), mode = level().kind as Mode, board = mode === "board", run = runFor(t.subject);
    if (!body) return;
    if (typeof run !== "string" && (board ? sc.bEdges.length : mode === "state" ? sc.planets.length : sc.mEdges.length)) {
      const { routes, pills, first } = traceLayout(run, placesOf(mode), edgeOf(mode), board, K), thick = 2.6 / Math.max(1, ZS);
      if (t.veil) {
        const m = cx.getTransform(), dpr = devicePixelRatio || 1;
        cx.setTransform(dpr, 0, 0, dpr, 0, 0);
        cx.fillStyle = "rgba(4,6,11,0.66)";
        cx.fillRect(0, 0, W, H);
        cx.setTransform(m);
      }
      for (const r of routes) {
        const { p0, c, p1 } = r.curve, g = cx.createLinearGradient(r.from.x, r.from.y, r.to.x, r.to.y);
        g.addColorStop(0, rgba(r.off ? OFF : r.from.color, 0.95));
        g.addColorStop(1, rgba(r.off ? OFF : r.to.color, 0.95));
        cx.strokeStyle = g;
        cx.lineWidth = thick;
        cx.setLineDash(r.off ? [5 / K, 5 / K] : []);
        cx.beginPath();
        for (let i = 0; i <= 24; i++) {
          const q = bez(p0, c, p1, r.t0 + ((r.t1 - r.t0) * i) / 24);
          if (i) cx.lineTo(q.x, q.y);
          else cx.moveTo(q.x, q.y);
        }
        cx.stroke();
        cx.setLineDash([]);
        arrow(bez(p0, c, p1, r.t1 - 0.02), bez(p0, c, p1, r.t1), rgba(r.off ? OFF : r.to.color, 0.95), 9);
      }
      // each visited state's rim and name firm up, with the time it held the task beside it
      for (const p of pills) {
        circle(p.place.x, p.place.y, p.place.r, rgba(p.place.color, 1), 2.2 / Math.max(1, ZS));
        if (mode !== "state") label(p.place.name, p.place.lab.x, p.place.lab.y, true, null, board ? 13 : 12.5); // a state level's bodies keep their own names
        pill(p.text, p.x, p.y, p.place.color);
      }
      for (const r of routes) badge(r.badge, r.nums, r.off ? OFF : TRACE);
      if (first) {
        circle(first.x, first.y, first.r, rgba(first.color, 0.9), 1.6 / Math.max(1, ZS));
        if (board) label(first.name, first.lab.x, first.lab.y, true, null, 13);
      }
      // on the Board, the lifecycle machines the task has sessions in: the moon is ringed with the count, and a sub-state it holds too
      if (board) {
        const ses = sessionRings(S.flows, t.subject.id, sc.moons, sc.subStates);
        for (const [m, n] of ses.moons) {
          circle(m.x, m.y, (m.r ?? 8) + 6, rgba(TRACE, 0.95), 1.6 / Math.max(1, ZS));
          text(`${n} session${n === 1 ? "" : "s"}`, m.x, m.y - (m.r ?? 8) - 14 / K, labPx(9.5), TRACE, "center", 600);
        }
        for (const m of ses.subs) circle(m.x, m.y, (m.r ?? 6) + 5, rgba(TRACE, 0.95), 1.4 / Math.max(1, ZS));
      }
    }
    circle(body.x, body.y, 9 / K, rgba(TRACE, 0.9), 1.6 / K);
    dot(body.x, body.y, 4.5 / K, rgba(tierColor(body.model), 1));
  }
  function drawScene(k: number, x: number, y: number) {
    const dpr = devicePixelRatio || 1;
    cx.setTransform(k * dpr, 0, 0, k * dpr, x * dpr, y * dpr);
    K = scene!.unit ? Math.max(k, 1 / scene!.unit) : k; // a zoomed-out Board draws its names at the size it laid them out at
    ZS = Math.max(1, k / fit.k);
    drawFold();
    drawGalaxies();
    drawMoons();
    drawBoardEdges();
    drawStateLinks();
    drawSun();
    drawPlanets();
    drawOwned();
    drawTasks();
    drawMachineEdges(scene!.mEdges);
    drawStates(scene!.mStates, true);
    drawMachineTasks();
    drawHangar();
    drawStars();
    drawTrace();
  }
  /** The header clock, ticked by a timer so it keeps time while the canvas is idle. */
  function paintClock() {
    const t = clockHms(Date.now(), prefs().clock), txt = live === "off" ? `○ reconnecting · ${t} MST` : `● live · ${t} MST`;
    if (txt !== clockText) els.clock.textContent = clockText = txt;
  }
  let wash: { w: number; h: number; g?: CanvasGradient } = { w: 0, h: 0 };
  const frame = (now: number) => {
    // The ambient clock (orbits, twinkle, dash drift) advances only across frames drawn back to back, so it freezes at rest and resumes where it stopped.
    clock += last ? Math.min(now - last, 100) / 1000 : 0;
    last = now;
    T = Date.now() / 1000;
    if (scene && grown.growing()) layout(true); // a state easing to a new size moves its neighbours, paths and the fit with it, frame by frame
    if (anim) anim(now);
    if (scene) update(clock);
    if (mouse && scene) setHover(hit((mouse.ox - view.x) / view.k, (mouse.oy - view.y) / view.k), mouse.cx, mouse.cy);
    else if (spotted && scene && !trans) hover = spotIn(scene, spotted) as Hover | null;
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
    if (now - tick > 250) {
      tick = now;
      heartbeat();
    }
  };
  /** Something still needs the next frame: a move or DAG run in flight, a fly-to, a level transition, or a body easing to a new size. */
  const busy = () => !!S && (animating({ now: T, moves: EVENTS(), dags: S.dags, flying: !!anim, transitioning: !!trans }) || grown.growing());
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
    if (!sc) return { path: pathKey(path), ready: false, canvas, panel: open, centre: { x: 0, y: 0 }, zoomed: false, targets: [], fit: fit.k, dags: [], states: [], hangar: null };
    const rect = (ax: number, ay: number, bx: number, by: number) => { const a = toScreen(view, { x: ax, y: ay }), b = toScreen(view, { x: bx, y: by }); return { x0: a.x, y0: a.y, x1: b.x, y1: b.y }; };
    const [x0, y0, x1, y1] = sc.box ?? [0, 0, sc.w, sc.h], at = (name: string, p: Pt, opens: Probe["targets"][number]["opens"] = "level") => ({ name, opens, ...toScreen(view, p) });
    const targets = l.kind === "board"
      ? [
          ...Object.values(sc.galaxies).map((g) => at(g.id, g)),
          ...sc.moons.map((m) => at(m.name, m)),
          ...sc.subStates.map((b) => at(`${b.machine}/${b.state}`, b)),
          ...Object.values(sc.stars).map((s) => at(s.name, s, s.fold ? "level" : "panel")),
          ...(sc.hangar ? [at("DAGs", sc.hangar)] : []),
          ...sc.tasks.filter((t) => !t.gone).map((t) => at(t.id, t, "panel")),
        ]
      : l.kind === "dags" || l.kind === "fold" ? Object.values(sc.stars).map((s) => at(s.name, s, "panel"))
      : [
          ...sc.planets.filter((p) => l.kind === "state" || p.anchor).map((p) => at(p.name, p)),
          ...(l.kind === "machine" ? sc.machineTasks.filter((t) => t._x !== undefined).map((t) => at(t.id, { x: t._x!, y: t._y! }, "panel")) : []),
        ];
    const board = l.kind === "board";
    const dags = board || l.kind === "dags" ? Object.values(sc.stars).map((s) => ({ name: s.name, ...rect(s.x - s.glyph.w / 2 - 10, s.y - s.glyph.h / 2 - 10, s.x + s.glyph.w / 2 + 10, s.y + s.glyph.h / 2 + 10) })) : [];
    const states = board ? Object.values(sc.galaxies).map((g) => ({ id: g.id, ...toScreen(view, g), r: g.R * view.k })) : [];
    return { path: pathKey(path), ready: !trans && !anim, canvas, panel: open, centre: toScreen(view, { x: (x0 + x1) / 2, y: (y0 + y1) / 2 }), zoomed: zoomedIn(view, fit), targets, fit: fit.k, dags, states, hangar: board && sc.hangar ? toScreen(view, sc.hangar) : null };
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
      stream = openStream({ snapshot: onSnapshot, live: onLive });
      clockTimer = window.setInterval(paintClock, 1000);
      paintClock();
    },
    stop() {
      stopped = true;
      loop.stop();
      stream?.close();
      clearTimeout(timer);
      clearInterval(timer);
      clearInterval(clockTimer);
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
      if (S) go(p, fx, fy, then);
    },
    fitView: () => {
      if (scene) flyTo(fit);
    },
    resize: () => {
      resize(true);
      frame(performance.now()); // resizing blanks the canvas: repaint in the same task, or the next frame shown is black
      wake();
    },
    openDag(name) {
      const d = S?.dagBy[name];
      if (d) openDagPanel({ ...d, group: S!.dagGroup[name] ?? "", runnable: S!.runnable.has(name) });
    },
    flyToGroup(name) {
      if (!S) return;
      const box = () => {
        const s = scene!.groups.find((g) => g.name === name)?.stars ?? [];
        if (!s.length) return fit;
        const xs = s.map((q) => q.x), ys = s.map((q) => q.y);
        return inFitBox(fitBox({ x0: Math.min(...xs) - 60, y0: Math.min(...ys) - 80, x1: Math.max(...xs) + 60, y1: Math.max(...ys) + 80 }, FW, H, Infinity, 0.9));
      };
      if (level().kind !== "dags") go([...BOARD, { kind: "dags" }], W / 2, H / 2, box);
      else flyTo(box());
    },
    spot(target) {
      spotted = target;
      if (!target) hover = null;
      loop.wake();
    },
    refresh() {
      if (!S) return;
      publish();
      heartbeat();
      paintClock();
    },
    selectTask(id) {
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
