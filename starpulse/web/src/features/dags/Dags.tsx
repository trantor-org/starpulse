// The DAGs view: a view of its own beside the Kanban, in the Kanban's frame. One stage with two panes that are a DAG's activity state:
// Processing on the left, the DAGs with a run in flight, and Idle on the right, every other DAG, with the latest to finish on top.
// A row is its status indicator, its name over its schedule and pool, its steps as the Star Map's DAG body (StarPulse's glyphs and flow lines),
// the pane's columns (a run's progress, or its last run and statistics) and, on a run-safe DAG, the Kanban's ▶ edge strip. A row has no hover; a click anywhere on it opens its modal. The rows are the stage's
// children, placed by transform, so a DAG whose state changes glides to its other pane rather than being drawn there afresh.
import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type RefObject } from "react";
import { createPortal } from "react-dom";
import { same } from "../../api/same";
import { DAG_PREFS_KEY, NO_DAG_FILTERS, useFilters } from "../../shared/viewPrefs";
import { DagModal } from "./DagModal";
import { IdleCells, Orb, RunCells, Strip, type LedgerGo } from "./DagParts";
import { captions, filterRows, panes, places, refusal, rows, short, type DagData, type DagFacts, type Row } from "./dagsModel";
import { ChoiceMenu } from "../../shared/ChoiceMenu";
import { useViewActive } from "../../shared/Kept";
import { SearchClear } from "../../shared/SearchClear";
import { PHONE } from "../../shared/nav";
import { BOARD, ledgerLevel, type Path } from "../../render/levels";
import { refused, startRun } from "../../render/panels";
import { Viewport } from "../../shared/ViewportRows";

type Post = Parameters<typeof startRun>[1];

/** The phone layout: a row takes two lines (the stylesheet's `max-width: 900px` query). */
const phone = () => window.matchMedia?.(PHONE).matches ?? false;
const onPhone = (change: () => void) => {
  const q = window.matchMedia?.(PHONE);
  q?.addEventListener("change", change);
  return () => q?.removeEventListener("change", change);
};

/** The width the two panes' fixed columns need side by side: Processing is 1 of 2.25 parts and Idle 1.25, each with its column sizes in the stylesheet. Text size moves it, so it reads `--fs`. */
const sideBySide = (fs: number) => {
  const edge = Math.max(30, 30 * fs);
  return 14 + Math.max(2.25 * (166 + 346 * fs + edge), 1.8 * (176 + 492 * fs + edge));
};

/** Whether the view is too narrow for two panes at this text size; a window too small for them stacks them, as a phone does. */
function useNarrow(ref: RefObject<HTMLElement | null>, live: boolean) {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const root = document.documentElement;
    const fit = () => setNarrow(el.clientWidth > 0 && el.clientWidth < sideBySide(parseFloat(root.style.getPropertyValue("--fs")) || 1));
    fit();
    const size = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    size?.observe(el);
    const scale = new MutationObserver(fit);
    scale.observe(root, { attributes: true, attributeFilter: ["style"] });
    return () => { size?.disconnect(); scale.disconnect(); };
  }, [ref, live]);
  return narrow;
}

/** Run now: the Kanban's ▶ edge strip on a run-safe DAG's row; none on the rest, as on a card that cannot start. */
function RunBtn({ r, why, run }: { r: Row; why: string | null; run: (r: Row) => void }) {
  if (!r.runSafe) return <span />;
  return (
    <button className="play edge" disabled={!!why} title={why ?? `Run ${short(r.d.name)} now`} aria-label={`Run ${short(r.d.name)} now`}
      onClick={(e) => { e.stopPropagation(); run(r); }}>▶</button>
  );
}

interface RowProps { r: Row; now: number; spot: boolean; why: string | null; f: DagFacts | undefined; run: (r: Row) => void; open: (r: Row) => void; pane: Pane; col: number; hs: number; slot: number; k: number; band: boolean; caption: string | null; glide: Glide | undefined }

/** One DAG's row, a slot on the stage: where it sits is three custom properties, so a move between panes is its transform's transition and the one element is the whole animation. It draws again only when what it shows changed: its row's reference holds while its DAG does, and its facts are compared by what they say. */
const DagRow = memo(function DagRow({ r, now, spot, why, f, run, open, pane, col, hs, slot, k, band, caption, glide }: RowProps) {
  const at = { "--c": col, "--hs": hs, "--s": slot, "--k": k, "--b": Number(band) } as CSSProperties;
  return (
    <div className={`drow p-${r.phase}${r.runSafe ? " startable" : ""}${spot ? " spot" : ""}`} data-dag={r.d.name} data-pane={pane} data-glide={glide} style={at} tabIndex={0} onClick={() => open(r)}
      onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && open(r)}>
      {caption && <span className="cap">{caption}</span>}
      <div className="body">
        <Orb phase={r.phase} />
        <span className="who"><span className="nm" title={r.d.name}>{short(r.d.name)}</span>
          <span className="sub">{f?.schedule ?? "manual"} · {r.d.pool ? `pool ${short(r.d.pool)}` : "no pool"}</span></span>
        <Strip r={r} w={220} h={30} />
        {pane === "processing" ? <RunCells r={r} now={now} /> : <IdleCells r={r} f={f} now={now} />}
        <RunBtn r={r} why={why} run={run} />
      </div>
    </div>
  );
}, (a, b) => (Object.keys(a) as (keyof RowProps)[]).every((k) => (k === "f" ? same(a.f, b.f) : a[k] === b[k])));

type Pane = "processing" | "idle";

/** Each pane's column labels after the status and DAG columns, as the mockup heads them. */
const COLUMNS: Record<Pane, string[]> = { processing: ["Steps", "Elapsed", "Progress"], idle: ["Steps", "Last run", "Runs/week", "Duration"] };
/** Which way a row glides: a finished DAG down into Just finished, a starting one down to the bottom of Processing. */
type Glide = "finish" | "start";
/** How long a glide's marker holds, a little past its 640ms transition. */
const GLIDE_MS = 720;

/** The DAGs that changed pane since the last snapshot, by the way they glide, for as long as the glide lasts. It is set in the render that moves the rows, so the first frame of the move already carries it; the first snapshot, whose rows were never in a pane, moves none. */
function useGlides(pane: Map<string, Pane>) {
  const [seen, setSeen] = useState(pane);
  const [moving, setMoving] = useState<Map<string, Glide>>(new Map());
  if (pane !== seen) {
    setSeen(pane);
    const moved = new Map<string, Glide>();
    for (const [name, to] of pane) {
      const from = seen.get(name);
      if (from && from !== to) moved.set(name, to === "idle" ? "finish" : "start");
    }
    if (moved.size) setMoving(moved);
  }
  useEffect(() => {
    if (!moving.size) return;
    const id = setTimeout(() => setMoving(new Map()), GLIDE_MS);
    return () => clearTimeout(id);
  }, [moving]);
  return moving;
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** The DAGs view. `spot` is the DAG a Recent line is hovered for: its row lights and scrolls into view. A new `opening` opens that DAG's modal. `filterSlot` is the navigator's filter slot, where the DAG filter draws; with none the view has no filter field. */
export function Dags({ data, post, openPath, spot = null, opening = null, filterSlot = null }: { data: DagData | null; post?: Post; openPath?: (p: Path) => void; spot?: string | null; opening?: { name: string } | null; filterSlot?: HTMLElement | null }) {
  // the filters survive a reload, so the view opens as it was left
  const [kept, keep] = useFilters(DAG_PREFS_KEY, NO_DAG_FILTERS);
  const { q, dom } = kept;
  const setQ = (v: string) => keep({ q: v }), setDom = (v: string | null) => keep({ dom: v });
  const [menu, setMenu] = useState(false);
  const filterBox = useRef<HTMLInputElement>(null);
  const [toast, setToast] = useState<{ text: string; n: number } | null>(null);
  const [starting, setStarting] = useState<Set<string>>(new Set());
  const [opened, setOpened] = useState<string | null>(null);
  const [refusedRun, setRefusedRun] = useState<string | null>(null);
  const [seenOpening, setSeenOpening] = useState(opening);
  if (opening !== seenOpening) {
    setSeenOpening(opening);
    if (opening) setOpened(opening.name);
  }
  useEffect(() => {
    if (spot) [...document.querySelectorAll<HTMLElement>("#stage .drow")].find((el) => el.dataset.dag === spot)?.scrollIntoView?.({ block: "nearest" });
  }, [spot]);
  // the server's clock, read at each snapshot and counted on between them, so a browser clock that is off does not skew "5m ago"
  const [now, setNow] = useState(data?.now ?? 0), [seen, setSeen] = useState(data?.now ?? 0);
  if (data && data.now !== seen) { setSeen(data.now); setNow(data.now); }
  // a view that is left stands still: it counts no seconds until it is shown again
  const active = useViewActive();
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [active]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(id);
  }, [toast]);

  const all = useMemo(() => (data ? rows(data) : []), [data]);
  // each snapshot decides the panes again, so a DAG whose run ended with no event to say so leaves Processing with the next one
  const rs = useMemo(() => filterRows(all, { q, dom }), [all, q, dom]);
  const split = useMemo(() => panes(rs), [rs]);
  const page = useRef<HTMLElement>(null);
  const phoned = useSyncExternalStore(onPhone, phone);
  const narrow = useNarrow(page, !!data);
  const small = phoned || narrow;
  const { at, bands } = useMemo(() => places(split, small), [split, small]);
  const pane = useMemo(() => new Map<string, Pane>([...split.processing.map((r) => [r.d.name, "processing"] as const), ...split.idle.map((r) => [r.d.name, "idle"] as const)]), [split]);
  const caps = useMemo(() => new Map([...captions(split.processing, split.fresh).map((c, i) => [split.processing[i].d.name, c] as const), ...captions(split.idle, split.fresh).map((c, i) => [split.idle[i].d.name, c] as const)]), [split]);
  const gliding = useGlides(pane);
  // the handlers a row holds keep their reference, so a row draws again for its own change and not for the view's
  const run = useCallback(async (r: Row) => {
    const name = r.d.name;
    setStarting((s) => new Set(s).add(name));
    const line = await startRun(name, post);
    setRefusedRun(refused(line));
    setStarting((s) => { const n = new Set(s); n.delete(name); return n; });
    setToast((t) => ({ text: `${short(name)}: ${line}`, n: (t?.n ?? 0) + 1 }));
  }, [post]);
  const openRow = useCallback((r: Row) => { setRefusedRun(null); setOpened(r.d.name); }, []);
  // a tie links to the Ledger of its transition, when the Board has one for the event; it reads `openPath` when clicked
  const go = useRef(openPath);
  useEffect(() => { go.current = openPath; });
  const flows = data?.flows, cues = data?.cues;
  const ledger = useCallback<LedgerGo>((ev) => {
    const level = go.current && ev && flows ? ledgerLevel({ flows, cues }, ev) : null;
    return level ? () => go.current!([...BOARD, level]) : null;
  }, [flows, cues]);
  if (!data) return <main id="dg" ref={page}><header><span className="title">DAGs</span><span className="count">no DAGs read</span></header></main>;

  const why = (r: Row) => refusal(r, starting.has(r.d.name));
  const shown = opened ? all.find((r) => r.d.name === opened) : undefined;
  const chip = (label: string, text: string | null) => (
    <span className={`fchip${text !== null ? " set" : ""}`} role="button" tabIndex={0} aria-haspopup="menu" aria-expanded={menu}
      onClick={() => setMenu((m) => !m)} onKeyDown={(e) => e.key === "Enter" && setMenu((m) => !m)}>
      {label}{text !== null && <>: <b>{text}</b></>} ▾
    </span>
  );
  // the stage's height: the header slots and the rows of its taller column, or of both stacked at a phone's width
  const stacked = Math.max(split.processing.length, 1) + split.idle.length;
  const stage = { "--hsum": small ? 2 : 1, "--n": small ? stacked : Math.max(split.processing.length, split.idle.length, 1), "--K": bands } as CSSProperties;
  const head = (id: Pane, title: string, n: number) => {
    const w = at.get(`${id}-head`)!;
    return (
      <div className="phead" data-pane={id} style={{ "--c": w.col, "--hs": w.hs, "--s": w.slot, "--k": w.k } as CSSProperties}>
        <span className="pt">{title}</span><span className="c">{n}</span>
        <span className="cols" aria-hidden="true"><span /><span>DAG</span>{COLUMNS[id].map((c) => <span key={c}>{c}</span>)}</span>
      </div>
    );
  };

  return (
    <main id="dg" ref={page}>
      <header>
        <span className="title">DAGs</span>
        <span className="count">{plural(all.length, "DAG")} · {plural(new Set(all.map((r) => r.domain)).size, "domain")}</span>
      </header>
      {filterSlot && createPortal(
        <div className="fw">
          <input id="dgq" ref={filterBox} type="text" placeholder="filter DAGs by name, step or domain…" aria-label="Filter DAGs by name, step or domain" autoComplete="off" spellCheck={false} value={q}
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setQ("")} />
          <SearchClear input={filterBox} value={q} clear={() => setQ("")} />
        </div>,
        filterSlot,
      )}
      <div className="filters">
        <div className="fw">
          {chip("Domain", dom)}
          {menu && (
            <ChoiceMenu title="Domain" options={[...new Set(all.map((r) => r.domain))].map((d) => ({ value: d, count: all.filter((r) => r.domain === d).length }))} value={dom}
              name={(v) => v} set={setDom} close={() => setMenu(false)} />
          )}
        </div>
        {(dom || q) && <button className="clear" onClick={() => keep(NO_DAG_FILTERS)}>clear</button>}
        <span className="shown">{rs.length === all.length ? `${all.length} shown` : `${rs.length} of ${all.length} shown`}</span>
      </div>
      {rs.length ? (
        <Viewport id="stage">
          <div className={`dstage${small ? " stack" : ""}`} style={stage}>
            {head("processing", "Processing", split.processing.length)}
            {head("idle", "Idle", split.idle.length)}
            {!split.processing.length && <div className="phint" style={{ "--c": 0, "--hs": 1, "--s": 0, "--k": at.get("processing-hint")!.k } as CSSProperties}>Nothing is running</div>}
            {rs.map((r) => {
              const w = at.get(r.d.name)!;
              return <DagRow key={r.d.name} r={r} now={now} spot={r.d.name === spot} why={why(r)} f={data.facts[r.d.name]} run={run} open={openRow}
                pane={pane.get(r.d.name)!} col={w.col} hs={w.hs} slot={w.slot} k={w.k} band={w.band} caption={caps.get(r.d.name) ?? null} glide={gliding.get(r.d.name)} />;
            })}
          </div>
        </Viewport>
      ) : <div className="none">No DAG matches the filters.</div>}
      {shown && <DagModal data={data} r={shown} now={now} starting={starting.has(shown.d.name)} refused={refusedRun} run={() => void run(shown)} close={() => setOpened(null)} ledger={ledger} />}
      {toast && <div className="dtoast" key={toast.n} role="status">{toast.text}</div>}
    </main>
  );
}
