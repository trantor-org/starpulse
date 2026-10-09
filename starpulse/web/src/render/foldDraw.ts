// A fold level's drawing: the Board path an event takes with the merge Ledger hung from it (the junction, the DAGs' rails, each template's caption,
// the rows with their scroll rail and strip, and `starpulse doctor`'s verdict), and what a merge sets off along it. It draws from the frame's
// context and primitives (draw.ts) and from what the renderer owns (`FoldIO`, read as it draws); the arrivals it tracks are its own.
import type { LedgerRow } from "../api";
import type { Contract } from "../features/level/contract";
import { freshKeys, optionalSteps, statusLine } from "../features/level/ledger";
import { bannerOf, type DoctorBox } from "../features/level/ledgerPanel";
import { pinsOf, portOf, withPins, type Pins } from "../features/level/ledgerPins";
import { AMBER, drawRows, CROSS, type Hits, type Ink } from "../features/level/ledgerRows";
import { begin, ease as easeScroll, fail, newScroll, place, receive, take, wantsPage, type Scroll } from "../features/level/ledgerScroll";
import { fetchMerges } from "../features/level/ledgerPage";
import { inView } from "../features/level/ledgerStrip";
import { drawStrip } from "../features/level/ledgerStripDraw";
import { rerunLine, type RerunStore } from "../features/level/rerun";
import type { AdminPrefs } from "../features/admin/adminPrefs";
import { ACT, DAG_COLOR, easeO, rgba, type Drawing, type DrawCtx } from "./draw";
import { FLARE, RING, type Moves, type Sky } from "./sky";
import { textW, type Scene, type Star } from "./scene";

/** The Ledger's colours by run state: an overdue cue is drawn as a failure, and another repository's unapplied merge as waiting. */
export const LEDGER_PALETTE: Record<string, string> = { ...DAG_COLOR, waiting: CROSS, overdue: DAG_COLOR.failed };

/** What the renderer owns and the fold's drawing reads as it draws, and the `doctor` box it records for the pointer; each is read when a frame draws, so the renderer's own state is never copied. */
export interface FoldIO {
  readonly S: Sky | null;
  readonly scene: Scene | null;
  /** Now, in seconds. */
  readonly T: number;
  readonly moves: Moves;
  readonly hotEdge: Set<string>;
  readonly contract: Contract;
  readonly rerunStore: RerunStore;
  hhmm(sec: number): string;
  prefs(): AdminPrefs;
  heldRows(): readonly LedgerRow[];
  focused(): LedgerRow | undefined;
  openRow(): LedgerRow | null;
  /** The fold is the level on screen, and no level change is running. */
  readonly onFold: boolean;
  /** Draw again: a page arrived. */
  wake(): void;
  doctor: DoctorBox | null;
}

export function foldDraw(dc: DrawCtx, d: Drawing, io: FoldIO) {
  const { cx } = dc;
  const { text, labPx, label, circle, dot, pulse, comet, flowLine, fitText, stroke, rail, arrow, body } = d;
  // A merge Ledger's scroll (ledgerScroll): every merge loaded and where the viewport sits on them, forgotten with the arrivals when the level has not been
  // drawn for a while, and where the pointer can take it (thumb, chip) as last drawn. `scrollGen` drops a page asked for before a forgetting; `scrollHeld`
  // is the rows the scroll was last given, taken again only when they change.
  let scroll: Scroll = newScroll(), scrollHeld: readonly LedgerRow[] | null = null, scrollGen = 0, scrollHits: Hits = { thumb: null, chip: null };
  /** The merge Ledger's viewport while one is on screen; null on any other level, and while a level is changing. */
  const ledgerGrid = () => (io.onFold ? io.scene?.fold?.ledger?.grid ?? null : null);
  /** The unresolved band as last drawn: the merges pinned above the rows, which scroll in the viewport left under it. */
  let pins: Pins = { shown: [], all: [], below: 0, failed: 0 };
  /** Where the rows scroll: the Ledger's viewport under the band. */
  const ledgerPort = () => {
    const grid = ledgerGrid();
    return grid ? portOf(grid, pins.shown.length) : null;
  };
  /** The rows the pointer can hit: the band's, then those scrolling in the viewport under it. */
  function ledgerShown() {
    const grid = ledgerGrid(), port = ledgerPort();
    if (!grid || !port) return [];
    const band = pins.shown.map((row, i) => ({ row, y: grid.top + grid.rh / 2 + i * grid.rh }));
    return [...band, ...place(scroll, port).filter((p) => p.y > port.top - port.rh / 2 && p.y < port.top + port.view + port.rh / 2)];
  }
  /** The Ledger scrolling or loading is something to animate: the offset easing, a page on its way, or a failed one waiting to be asked again. */
  const scrolling = () => !!ledgerGrid() && (scroll.y !== scroll.ty || scroll.fetching || (scroll.more && scroll.retryAt > dc.clock));
  /** The footer row came into view: ask for the merges older than the oldest held. */
  function askPage() {
    const gen = scrollGen, before = scroll.rows.at(-1)?.at;
    if (before === undefined) return;
    scroll = begin(scroll);
    void fetchMerges(before).then((page) => {
      if (gen !== scrollGen) return;
      scroll = page ? receive(scroll, page.merges, page.more) : fail(scroll, dc.clock);
      io.wake();
    });
  }
  const dagHeat = (n: string) => {
    const d = io.S!.dagBy[n];
    if (!d) return 0;
    if (d.status === "running") return 1;
    const f = io.moves.flare[n];
    return f !== undefined && f <= io.T ? Math.max(0, 1 - (io.T - f) / FLARE) : 0;
  };
  // A Ledger's arrivals: the rows it held at the last look (null until a look, so a page opened or a level entered shows its rows still), each new row's
  // clock, and the rings and comets its merge sets off along the path. A level not drawn for a while forgets what it held.
  let ledgerSeen: Set<string> | null = null, ledgerAt = 0;
  const arrived = new Map<string, number>(), ledgerFx: { x: number; y: number; r: number; t0: number; col: string; grow: number }[] = [], ledgerComets: number[] = [];
  let scrollAt = 0, scrollView = "";
  const rowInk: Ink = {
    star4: (x, y, r, col) => {
      cx.fillStyle = col;
      cx.beginPath();
      for (let i = 0; i < 8; i++) {
        const a = (i * Math.PI) / 4 - Math.PI / 2, d = i % 2 ? r * 0.4 : r;
        cx[i ? "lineTo" : "moveTo"](x + d * Math.cos(a), y + d * Math.sin(a));
      }
      cx.closePath();
      cx.fill();
    },
    text, fit: fitText, stroke, circle: (x, y, r, col, w) => circle(x, y, r, col, w), dot, pulse: (x, y, r, age, col, grow) => pulse(x, y, r, age, col, grow),
    width: (s, size, weight = 400) => {
      cx.font = `${weight} ${size}px Inter, system-ui, sans-serif`;
      return cx.measureText(s).width;
    },
    arc: (x, y, r, from, to, col, w) => {
      cx.strokeStyle = col;
      cx.lineWidth = w;
      cx.beginPath();
      cx.arc(x, y, r, from, to);
      cx.stroke();
    },
    rect: (b, fill, line, w = 1) => {
      cx.fillStyle = fill;
      cx.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
      if (!line) return;
      cx.strokeStyle = line;
      cx.lineWidth = w / dc.K;
      cx.strokeRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
    },
    clip: (b, draw) => {
      cx.save();
      cx.beginPath();
      cx.rect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
      cx.clip();
      draw();
      cx.restore();
    },
  };
  /** A merge arrived: ring the junction, send a comet down the path and ring the event's mark and the second state as it passes. */
  function arrive(led: NonNullable<NonNullable<Scene["fold"]>["ledger"]>, f: NonNullable<Scene["fold"]>) {
    const at = { x: led.J.x, y: led.J.y };
    ledgerFx.push({ ...at, r: 6, t0: dc.clock, col: ACT, grow: 30 }, { x: led.mark.x, y: led.mark.y, r: 6, t0: dc.clock + 0.7, col: ACT, grow: 30 }, { x: f.b!.x, y: f.b!.y, r: f.b!.r, t0: dc.clock + 1.6, col: f.b!.color, grow: 30 });
    ledgerComets.push(dc.clock);
  }
  function drawFx(f: NonNullable<Scene["fold"]>) {
    for (let i = ledgerFx.length - 1; i >= 0; i--) {
      const p = ledgerFx[i], age = (dc.clock - p.t0) / RING;
      if (age > 1.3) ledgerFx.splice(i, 1);
      else if (age > 0) pulse(p.x, p.y, p.r, age, p.col, p.grow);
    }
    for (let i = ledgerComets.length - 1; i >= 0; i--) {
      const u = (dc.clock - ledgerComets[i]) / 1.6;
      if (u >= 1) ledgerComets.splice(i, 1);
      else comet(f.p0!, { x: (f.p0!.x + f.p1!.x) / 2, y: f.p0!.y }, f.p1!, easeO(u), 3.4, ACT);
    }
  }
  // a fold's level: the Board path an event takes, with the Ledger hung from it. Under the path's first state the PR (or task) that moves it meets
  // the junction every rail leaves from; the DAG that writes the event is fed straight from it and ties up to the event's mark on the path, and
  // each cue hangs off a bus below the templates. Each template keeps its own column, its caption stating the contract it declares.
  /** `starpulse doctor`'s verdict on the contract, right-aligned at (x, y); hover for what it checked, or the key to add. */
  function drawDoctor(x: number, y: number) {
    const report = io.contract.report(), banner = bannerOf(report);
    if (!report || !banner) return;
    const col = banner.tone === "ok" ? DAG_COLOR.succeeded : banner.tone === "warn" ? AMBER : DAG_COLOR.failed, hot = dc.hover?.kind === "ldoctor", head = labPx(10.5), sub = labPx(10);
    text(banner.head, x, y, head, rgba(col, hot ? 1 : 0.85), "right", 500);
    text(banner.sub, x, y + 14 / dc.K, sub, rgba("#94a3b8", hot ? 0.8 : 0.55), "right");
    const w = Math.max(textW(banner.head, head), textW(banner.sub, sub));
    io.doctor = { x0: x - w, y0: y - 9 / dc.K, x1: x, y1: y + 22 / dc.K, report };
  }
  function drawFold() {
    io.doctor = null;
    const f = io.scene!.fold, led = f?.ledger;
    if (!f?.a || !f.b || !f.p0 || !f.p1 || !led) return;
    const { a, b, p0, p1 } = f, sc = io.scene!, named = dc.hover?.kind === "dag" ? dc.hover.o.name : dc.hover?.kind === "caption" ? dc.hover.o.dag : null, lit = !!named;
    const heat = (n: string) => dagHeat(n), top = led.J.y - Math.min(...Object.values(sc.stars).map((s) => s.glyph.h)) / 2 - 50 / dc.K, grid = led.grid;
    const bottom = grid ? grid.top + grid.view : led.bus + 30 / dc.K;
    // a merge that landed since the last look arrives: its row lowers in and rings, and its comet runs the path
    const held = io.S?.ledgers[led.event] ?? [];
    if (dc.clock - ledgerAt > 1.5) ledgerSeen = null;
    ledgerAt = dc.clock;
    for (const k of freshKeys(ledgerSeen, held)) {
      arrived.set(k, dc.clock);
      arrive(led, f);
    }
    ledgerSeen = new Set(held.map((r) => r.key));
    // the rows scroll under the templates: the head the server sent joins the merges loaded, the offset eases, and the footer coming into view asks for a page
    if (grid) {
      if (dc.clock - scrollAt > 1.5) { scroll = newScroll(); scrollHeld = null; scrollGen++; }
      // an unresolved failure pins above the rows, and the rows scroll past it in what the band leaves
      pins = pinsOf([...held, ...scroll.rows], io.S?.mergePins ?? [], grid.cap);
      scroll = withPins(scroll, pins);
      const port = portOf(grid, pins.shown.length), dt = Math.min(0.1, dc.clock - scrollAt), shape = `${port.view}/${port.rh}`;
      if (held !== scrollHeld || shape !== scrollView) [scroll, scrollHeld, scrollView] = [take(scroll, held, port), held, shape];
      [scroll, scrollAt] = [easeScroll(scroll, dt), dc.clock];
      if (wantsPage(scroll, port, dc.clock)) askPage();
    }
    const hairs = rgba("#94a3b8", 0.1), writer = led.cols.find((c) => c.role === "writer");
    // the grid: a column down from each template, and the spine the junction hangs from
    for (const c of led.cols) stroke([{ x: c.x0, y: top }, { x: c.x0, y: bottom }], hairs);
    stroke([{ x: led.J.x, y: led.J.y + 8 / dc.K }, { x: led.J.x, y: bottom }], rgba(ACT, 0.35), 1.4);
    if (led.rows === "merge") {
      const lane = grid?.lane ?? led.J.x + 22 / dc.K;
      stroke([{ x: lane, y: led.bus + 4 / dc.K }, { x: lane, y: bottom }], rgba(CROSS, 0.35), 1, [2, 4]);
      text("other repos", lane + 4 / dc.K, led.bus + 14 / dc.K, labPx(9.5), rgba(CROSS, 0.6), "left");
    }
    // the path, with an arrow into the second state
    flowLine({ ...p0, color: a.color }, { ...p1, color: b.color }, (lit ? 0.75 : 0.4) + Math.max(0, ...led.cols.map((c) => heat(c.dag))) * 0.4, Math.max(io.hotEdge.has(`board:${a.id}>${b.id}`) ? 1 : 0, ...led.cols.map((c) => heat(c.dag))) + (lit ? 0.5 : 0));
    cx.beginPath();
    cx.moveTo(p0.x, p0.y);
    cx.lineTo(p1.x, p1.y);
    cx.stroke();
    cx.setLineDash([]);
    arrow(p0, p1, rgba(b.color, 0.6), 7 / Math.max(1, dc.ZS) * dc.K);
    for (const e of [a, b]) body(e, false);
    text(a.name, a.x - a.r - 14 / dc.K, a.y, labPx(13), rgba("#cfd9ea", 0.85), "right");
    label(b.name, b.x, b.y + b.r + 24 / dc.K, false, null, 13);
    // the event's mark on the path, and the DAG that writes it tied up to it
    const r = 4.5 / dc.K ** 0.5, hotMark = !!writer && named === writer.dag;
    dot(led.mark.x, led.mark.y, r, "rgba(6,10,20,0.95)");
    circle(led.mark.x, led.mark.y, r, rgba(ACT, hotMark ? 1 : 0.7), 1.3 / dc.K ** 0.5);
    text(led.event, led.mark.x, led.mark.y - 14 / dc.K, labPx(11), rgba("#dbe4f3", 0.8), "center", 500);
    const rootOf = (s: Star) => ({ x: s.x + s.glyph.nodes[0].x, y: s.y + s.glyph.nodes[0].y }), nrOf = (s: Star) => (s.glyph.nodes.length === 1 ? 5.5 : 4);
    for (const c of led.cols) if (c.role === "writer") {
      const s = sc.stars[c.dag];
      stroke([{ x: s.x, y: s.y - s.glyph.h / 2 - nrOf(s) - 3 / dc.K }, { x: led.mark.x, y: led.mark.y + 6 / dc.K }], rgba(ACT, 0.7), 1.2, [2, 4]);
    }
    if (writer) text(`writes ${led.event}`, sc.stars[writer.dag].x + 8 / dc.K, (sc.stars[writer.dag].y + led.mark.y) / 2 + 6 / dc.K, labPx(10.5), rgba(ACT, 0.8), "left");
    // the junction: the PR (or task) that moves the path's first state meets it, and every rail leaves from it
    const jr = 6 / dc.K ** 0.5, mergeRow = led.rows === "merge";
    rail([{ x: a.x, y: a.y + a.r + 4 / dc.K }, { x: led.J.x, y: led.J.y - 9 / dc.K, c: { x: a.x, y: (a.y + led.J.y) / 2 } }], a.color, ACT, 0, false);
    cx.save();
    cx.translate(led.J.x, led.J.y);
    cx.rotate(Math.PI / 4);
    cx.fillStyle = "rgba(6,10,20,0.95)";
    cx.fillRect(-jr, -jr, 2 * jr, 2 * jr);
    cx.strokeStyle = rgba(ACT, 0.8);
    cx.lineWidth = 1.4 / dc.K ** 0.5;
    cx.strokeRect(-jr, -jr, 2 * jr, 2 * jr);
    cx.restore();
    text(mergeRow ? "merge to main" : led.event, led.J.x - 16 / dc.K, led.J.y, labPx(12.5), rgba("#dbe4f3", 0.85), "right", 500);
    text(mergeRow ? "PR merges" : "task moves", a.x - 8 / dc.K, (a.y + a.r + led.J.y) / 2, labPx(10.5), rgba("#94a3b8", 0.55), "right");
    // the rails: the writer straight from the junction, every other DAG off the bus under the templates
    const feeds = led.cols.filter((c, i) => c.role === "cue" || i > 0);
    if (writer && led.cols[0] === writer) {
      const s = sc.stars[writer.dag], root = rootOf(s);
      rail([{ x: led.J.x + 9 / dc.K, y: led.J.y }, { x: root.x - nrOf(s) - 3 / dc.K, y: root.y }], ACT, ACT, heat(writer.dag), false);
    }
    for (const c of feeds) {
      const s = sc.stars[c.dag], root = rootOf(s);
      rail([{ x: led.J.x, y: led.bus }, { x: root.x - 40 / dc.K, y: led.bus }, { x: root.x - nrOf(s) - 2 / dc.K, y: root.y, c: { x: root.x - 14 / dc.K, y: led.bus } }], ACT, ACT, heat(c.dag), c.role === "cue");
    }
    if (feeds.length) text(mergeRow ? "cue · each merge to main" : `cue · each ${led.event}`, led.J.x + 10 / dc.K, led.bus - 8 / dc.K, labPx(10), rgba("#94a3b8", 0.55), "left");
    if (mergeRow) drawDoctor(led.J.x - 16 / dc.K, led.bus - 12 / dc.K);
    // each template's caption: the contract it declares, cut to its column, and under it the merge in focus
    const byKey = new Map(io.heldRows().map((r) => [r.key, r])), fm = io.focused(), newest = held.find((r) => r.appliedBy === undefined);
    for (const c of led.cols) {
      const s = sc.stars[c.dag], hot = named === c.dag, size = labPx(10.5), y = s.y + s.glyph.h / 2 + 16 / dc.K, max = c.x1 - c.x0 - 8 / dc.K;
      const lines = [c.role === "writer" ? `on ${c.on}` : `cue · on ${c.on}`, ...(c.resolves ? [`clears on ${c.resolves === "forced" ? "forced rerun" : "next success"}`] : [])];
      // under the name, a line apart at the text size, so the lines never meet at 150%
      lines.forEach((t, i) => text(fitText(t, max, size), s.x, y + labPx(15 + 15 * i), size, rgba("#94a3b8", hot ? 0.9 : 0.6), "center"));
      if (!fm) continue;
      const ln = statusLine(fm, c, fm.runs[c.dag], { event: led.event, now: io.T, hm: io.hhmm, optional: optionalSteps(held, c.dag), by: (k) => byKey.get(k) });
      text(fitText(`${fm === newest ? "newest" : io.hhmm(fm.at)} ${(fm.sha ?? fm.key).slice(0, 7)} · ${ln.main}`, max, size), s.x, y + labPx(15 + 15 * lines.length), size, rgba(ln.state ? DAG_COLOR[ln.state] ?? CROSS : "#94a3b8", 0.85), "center");
    }
    // the merge rows, each template's cell beside its run's mini step graph; a row still arriving counts its own seconds
    if (grid) {
      const age = (key: string) => {
        const t0 = arrived.get(key);
        if (t0 === undefined) return undefined;
        if (dc.clock - t0 > 2) return void arrived.delete(key);
        return dc.clock - t0;
      };
      scrollHits = drawRows(rowInk, {
        led, glyphs: Object.fromEntries(led.cols.map((c) => [c.dag, sc.stars[c.dag].glyph])), ctx: { event: led.event, now: io.T, hm: io.hhmm, by: (k) => byKey.get(k) },
        optional: Object.fromEntries(led.cols.map((c) => [c.dag, optionalSteps(scroll.rows, c.dag)])), px: labPx, palette: LEDGER_PALETTE, clock: dc.clock, age, scroll: scroll,
        lit: dc.hover?.kind === "lrow" ? dc.hover.o.key : io.openRow()?.key, pins: pins, rerunning: rerunLine(io.rerunStore.state.started, io.S?.dags ?? [], io.T),
        title: (id) => io.S?.settled[id]?.title ?? io.S?.board.agents.find((a) => a.id === id)?.title,
      });
      if (io.S?.mergeStrip) {
        const day = io.heldRows().filter((r) => r.at > io.T - 86400).length;
        drawStrip(rowInk, { led, data: io.S.mergeStrip, pins: pins.all, inView: inView(scroll, portOf(grid, pins.shown.length)), loaded: day, now: io.T, mode: io.prefs().clock, px: labPx, palette: { ...DAG_COLOR } });
      }
    }
    drawFx(f);
  }
  return {
    drawFold, ledgerGrid, ledgerPort, ledgerShown, scrolling,
    get scroll() { return scroll; }, set scroll(v) { scroll = v; }, get scrollHeld() { return scrollHeld; }, get scrollHits() { return scrollHits; },
  };
}
