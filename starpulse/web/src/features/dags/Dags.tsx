// The DAGs view: a view of its own beside the Kanban, in the Kanban's frame. A catalog with a fold per domain and a row per DAG:
// its state dot, its steps as a small constellation, its last run, its pool and its first Board tie, and on a run-safe row the
// Kanban's ▶ edge strip. It reuses the Kanban's filter chips, menus and folds, and the Star Map's DAG colors (DAG_COLOR).
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { DAG_PREFS_KEY, NO_DAG_FILTERS, useFilters } from "../../shared/viewPrefs";
import { DagModal } from "./DagModal";
import { lastLine, Orb, poolText, Strip, TieChip, type LedgerGo } from "./DagParts";
import { filterRows, group, order, PHASES, RECENCY, recent, refusal, rows, short, ties, type DagData, type Phase, type Row } from "./dags";
import { ChoiceMenu } from "../../shared/ChoiceMenu";
import { BOARD, ledgerLevel, type Path } from "../../render/levels";
import { refused, startRun } from "../../render/panels";
import { DAG_COLOR } from "../../render/renderer";

type Post = Parameters<typeof startRun>[1];

/** Run now: the Kanban's ▶ edge strip on a run-safe DAG's row; none on the rest, as on a card that cannot start. */
function RunBtn({ r, why, run }: { r: Row; why: string | null; run: (r: Row) => void }) {
  if (!r.runSafe) return <span />;
  return (
    <button className="play edge" disabled={!!why} title={why ?? `Run ${short(r.d.name)} now`} aria-label={`Run ${short(r.d.name)} now`}
      onClick={(e) => { e.stopPropagation(); run(r); }}>▶</button>
  );
}

function Fold({ k, title, n, folded, toggle, children }: { k: string; title: ReactNode; n: number; folded: Set<string>; toggle: (k: string) => void; children: ReactNode }) {
  const f = folded.has(k);
  return (
    <div className={`bucket${f ? " folded" : ""}`}>
      <div className="bh" onClick={() => toggle(k)} role="button" tabIndex={0} aria-expanded={!f}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle(k))}><span className="tw">▾</span><span className="bn">{title}</span><span className="c">{n}</span></div>
      {!f && children}
    </div>
  );
}

/** How many DAGs are running (queued with them), failing and never run; the healthy are the rule and go uncounted. */
function Census({ rs }: { rs: Row[] }) {
  return (
    <span className="census">
      {PHASES.filter(([p]) => p !== "ok").map(([p, l]) => {
        const n = rs.filter((r) => group(r.phase) === p).length;
        return n ? <span key={p} title={`${n} ${l.toLowerCase()}`}><Orb phase={p} />{n}</span> : null;
      })}
    </span>
  );
}

function Catalog({ data, rs, now, why, run, open, ledger, folded, toggle, spot }: {
  data: DagData; rs: Row[]; now: number; spot: string | null; why: (r: Row) => string | null; run: (r: Row) => void; open: (r: Row) => void; ledger?: LedgerGo; folded: Set<string>; toggle: (k: string) => void;
}) {
  const doms = [...new Set([...data.domains.map((d) => d.name), ...rs.map((r) => r.domain)])].filter((d) => rs.some((r) => r.domain === d));
  return (
    <div id="catalog">
      <div className="thead"><span /><span>DAG</span><span>Steps</span><span>Last run</span><span>Pool</span><span>Board</span><span /></div>
      {doms.map((d) => {
        const list = rs.filter((r) => r.domain === d).sort(order);
        return (
          <Fold key={d} k={`cat|${d}`} title={<>{d} <Census rs={list} /></>} n={list.length} folded={folded} toggle={toggle}>
            {list.map((r) => {
              const t = ties(data, r.d.name)[0];
              return (
                <div key={r.d.name} className={`trow p-${r.phase}${r.runSafe ? " startable" : ""}${r.d.name === spot ? " spot" : ""}`} data-dag={r.d.name} tabIndex={0} onClick={() => open(r)}
                  onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && open(r)}>
                  <Orb phase={r.phase} /><span className="nm" title={r.d.name}>{short(r.d.name)}</span><Strip r={r} />
                  <span className="last">{lastLine(r, now)}</span><span className="pool">{poolText(data.pools, r) || "—"}</span>
                  <span>{t ? <TieChip t={t} ledger={ledger} /> : <span className="none">—</span>}</span>
                  <RunBtn r={r} why={why(r)} run={run} />
                </div>
              );
            })}
          </Fold>
        );
      })}
    </div>
  );
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** The DAGs view. `spot` is the DAG a Recent line is hovered for: its row lights as a hovered row does and scrolls into view. A new `opening` opens that DAG's modal. */
export function Dags({ data, post, openPath, spot = null, opening = null }: { data: DagData | null; post?: Post; openPath?: (p: Path) => void; spot?: string | null; opening?: { name: string } | null }) {
  // the filters survive a reload, so the view opens as it was left
  const [kept, keep] = useFilters(DAG_PREFS_KEY, NO_DAG_FILTERS);
  const { q, dom, win } = kept, only = kept.only as Exclude<Phase, "queued"> | null;
  const setQ = (v: string) => keep({ q: v }), setOnly = (v: typeof only) => keep({ only: v }), setDom = (v: string | null) => keep({ dom: v }), setWin = (v: string | null) => keep({ win: v });
  const [menu, setMenu] = useState<"status" | "domain" | "recency" | null>(null);
  const [folded, setFolded] = useState<Set<string>>(new Set());
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
    if (spot) [...document.querySelectorAll<HTMLElement>("#catalog .trow")].find((el) => el.dataset.dag === spot)?.scrollIntoView?.({ block: "nearest" });
  }, [spot]);
  // the server's clock, read at each snapshot and counted on between them, so a browser clock that is off does not skew "5m ago"
  const [now, setNow] = useState(data?.now ?? 0), [seen, setSeen] = useState(data?.now ?? 0);
  if (data && data.now !== seen) { setSeen(data.now); setNow(data.now); }
  useEffect(() => {
    const id = setInterval(() => setNow((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(id);
  }, [toast]);

  const all = useMemo(() => (data ? rows(data) : []), [data]);
  if (!data) return <main id="dg"><header><span className="title">DAGs</span><span className="count">no DAGs read</span></header></main>;

  const why = (r: Row) => refusal(r, starting.has(r.d.name));
  const run = async (r: Row) => {
    const name = r.d.name;
    setStarting((s) => new Set(s).add(name));
    const line = await startRun(name, post);
    setRefusedRun(refused(line));
    setStarting((s) => { const n = new Set(s); n.delete(name); return n; });
    setToast((t) => ({ text: `${short(name)}: ${line}`, n: (t?.n ?? 0) + 1 }));
  };
  // a tie links to the Ledger of its transition, when the Board has one for the event
  const ledger: LedgerGo = (ev) => {
    const level = openPath && ev ? ledgerLevel(data, ev) : null;
    return level ? () => openPath!([...BOARD, level]) : null;
  };
  const cutoff = (label: string) => now - RECENCY.find(([l]) => l === label)![1];
  const rs = filterRows(all, { q, only, dom, since: win ? cutoff(win) : 0 });
  const shown = opened ? all.find((r) => r.d.name === opened) : undefined;
  // the Kanban's filter chip: a label, the chosen value, ▾; a press opens its menu
  const chip = (name: "status" | "domain" | "recency", label: string, text: string | null) => (
    <span className={`fchip${text !== null ? " set" : ""}`} role="button" tabIndex={0} aria-haspopup="menu" aria-expanded={menu === name}
      onClick={() => setMenu((m) => (m === name ? null : name))} onKeyDown={(e) => e.key === "Enter" && setMenu((m) => (m === name ? null : name))}>
      {label}{text !== null && <>: <b>{text}</b></>} ▾
    </span>
  );
  const toggle = (k: string) => setFolded((f) => { const n = new Set(f); if (!n.delete(k)) n.add(k); return n; });

  return (
    <main id="dg">
      <header>
        <span className="title">DAGs</span>
        <span className="count">{plural(all.length, "DAG")} · {plural(new Set(all.map((r) => r.domain)).size, "domain")}</span>
        <span className="sky"><Census rs={all} /></span>
      </header>
      <div className="filters">
        <div className="fw">
          <input id="dgq" type="text" placeholder="filter by name, step or domain…" aria-label="Filter DAGs by name, step or domain" autoComplete="off" spellCheck={false} value={q}
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setQ("")} />
        </div>
        <div className="fw">
          {chip("status", "Status", only && PHASES.find(([p]) => p === only)![1])}
          {menu === "status" && (
            <ChoiceMenu title="Status" options={PHASES.map(([p]) => ({ value: p, count: all.filter((r) => group(r.phase) === p).length }))} value={only}
              name={(v) => PHASES.find(([p]) => p === v)![1]} set={(v) => setOnly(v as typeof only)} close={() => setMenu(null)} />
          )}
        </div>
        <div className="fw">
          {chip("domain", "Domain", dom)}
          {menu === "domain" && (
            <ChoiceMenu title="Domain" options={[...new Set(all.map((r) => r.domain))].map((d) => ({ value: d, count: all.filter((r) => r.domain === d).length }))} value={dom}
              name={(v) => v} set={setDom} close={() => setMenu(null)} />
          )}
        </div>
        <div className="fw">
          {chip("recency", "Last run", win)}
          {menu === "recency" && (
            <ChoiceMenu title="Last run" options={RECENCY.map(([l]) => ({ value: l, count: all.filter((r) => recent(r, cutoff(l))).length }))} value={win}
              name={(v) => v} set={setWin} close={() => setMenu(null)} />
          )}
        </div>
        {(only || dom || win || q) && <button className="clear" onClick={() => keep(NO_DAG_FILTERS)}>clear</button>}
        <span className="shown">{rs.length === all.length ? `${all.length} shown` : `${rs.length} of ${all.length} shown`}</span>
      </div>
      {rs.length ? <Catalog data={data} rs={rs} now={now} spot={spot} why={why} run={run} ledger={ledger} open={(r) => { setRefusedRun(null); setOpened(r.d.name); }} folded={folded} toggle={toggle} /> : <div className="none">No DAG matches the filters.</div>}
      {shown && <DagModal data={data} r={shown} now={now} starting={starting.has(shown.d.name)} refused={refusedRun} run={() => void run(shown)} close={() => setOpened(null)} ledger={ledger} />}
      {toast && <div className="dtoast" key={toast.n} role="status">{toast.text}</div>}
    </main>
  );
}

const key = (c: string): CSSProperties => ({ color: c });

/** The legend panel's lines for this view. */
export function DagLegend() {
  return (
    <>
      <span><Orb phase="running" />running</span><span><Orb phase="ok" />healthy</span><br />
      <span><Orb phase="failed" />last run failed</span><span><Orb phase="idle" />never run</span><br />
      <span><svg width="26" height="8" aria-hidden="true"><line x1="3" y1="4" x2="23" y2="4" className="e" /><circle cx="3" cy="4" r="2.4" fill={DAG_COLOR.succeeded} /><circle cx="13" cy="4" r="2.8" fill={DAG_COLOR.running} /><circle cx="23" cy="4" r="2.4" className="hollow" /></svg> steps</span>
      <span><svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="2.4" fill={DAG_COLOR.succeeded} /><circle cx="5" cy="5" r="4.3" className="ring" /></svg> agent step</span><br />
      <span><span style={key("var(--agent)")}>⇢</span> Board tie</span><span><span style={key("var(--ok)")}>▶</span> run-safe</span>
    </>
  );
}
