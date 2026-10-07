// The DAGs view: a view of its own beside the Kanban, in the Kanban's frame. A catalog with a fold per domain and a row per DAG:
// its state dot, its steps as a small constellation, its last run, its pool and its first Board tie, and on a run-safe row the
// Kanban's ▶ edge strip. It reuses the Kanban's filter chips, menus and folds, and the Star Map's DAG colors (DAG_COLOR).
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { ago, filterRows, group, order, PHASES, place, rows, short, ties, took, type DagData, type Phase, type Row, type Tie } from "./dags";
import { ChoiceMenu } from "./Kanban";
import { startRun } from "./panels";
import { DAG_COLOR } from "./renderer";
import type { Pool } from "./types";

type Post = Parameters<typeof startRun>[1];

/** A DAG's state as a dot in the Star Map's DAG colors: amber and pulsing while it runs, a black hole when its last run failed, hollow before its first run. */
const Orb = ({ phase }: { phase: Phase }) => <i className={`orb o-${phase}`} aria-hidden="true" />;

/** A name cut to `n` characters with an ellipsis: the strip draws outside its box, so its text must fit. */
const fit = (t: string, n: number) => (t.length <= n ? t : `${t.slice(0, Math.max(1, Math.floor(n) - 1))}…`);
const labelPx = () => 6.1 * (Number(getComputedStyle(document.documentElement).getPropertyValue("--fs")) || 1);

/** A DAG's steps as a constellation: one star per step in its status colour, joined by its dependencies; the running step burns. */
export function Strip({ r, w = 220, h = 20 }: { r: Row; w?: number; h?: number }) {
  const st = r.d.steps;
  const p = place(st, w, h, 7, 3, 5.5, 34, Math.min(7, (h - 6) / 2));
  const rr = st.length > 9 ? 2.1 : 2.8;
  return (
    <svg className="dstrip" width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMinYMid meet" aria-hidden="true">
      {st.flatMap((s) => s.depends.filter((d) => p.at[d]).map((d) => (
        <line key={d + ">" + s.name} x1={p.at[d].x} y1={p.at[d].y} x2={p.at[s.name].x} y2={p.at[s.name].y} className={r.steps[s.name] === "running" ? "e hot" : "e"} />
      )))}
      {st.map((s) => {
        const v = r.steps[s.name] ?? "not_started", c = DAG_COLOR[v] ?? "var(--track)", { x, y } = p.at[s.name];
        return (
          <g key={s.name} className={`sd s-${v}`}>
            {v === "running" && <circle cx={x} cy={y} r={rr * 2.6} fill={c} className="halo" />}
            <circle cx={x} cy={y} r={v === "running" ? rr * 1.2 : rr} fill={v === "not_started" ? "var(--pop)" : c} stroke={v === "not_started" ? "var(--faint)" : "none"} strokeWidth={0.8} />
            {s.kind === "agent" && <circle cx={x} cy={y} r={rr + 2} fill="none" stroke="var(--agent)" strokeWidth={0.7} />}
          </g>
        );
      })}
      {st.length === 1 && <text x={16} y={h / 2 + 3.5} className="one">{fit(st[0].name, (w - 22) / (labelPx() * 0.88))}</text>}
    </svg>
  );
}

/** What a row's last-run cell says: the step a run is in and for how long, the step a run failed at, or when the last run ended and how long it took. */
export function lastLine(r: Row, now: number): ReactNode {
  if (r.phase === "running") return <><b className="hot">{r.step || "starting"}</b> · {took(r.startedAt, now)}</>;
  if (r.phase === "queued") return <b className="q">queued</b>;
  if (r.phase === "idle") return "never run";
  if (r.phase === "failed") {
    const at = Object.entries(r.steps).find(([, v]) => v === "failed" || v === "aborted")?.[0];
    return <><span className="bad">{r.d.status === "aborted" ? "aborted" : "failed"}{at ? ` at ${at}` : ""}</span> · {ago(now, r.finishedAt)}</>;
  }
  return <>{ago(now, r.finishedAt)} · {took(r.startedAt, r.finishedAt)}</>;
}

export const poolText = (pools: Pool[], r: Row) => {
  const p = pools.find((x) => x.name === r.d.pool);
  return p ? `${short(p.name)} ${p.running}/${p.cap}${p.queued ? ` +${p.queued}` : ""}` : "";
};

/** Run now: the Kanban's ▶ edge strip on a run-safe DAG's row; none on the rest, as on a card that cannot start. */
function RunBtn({ r, why, run }: { r: Row; why: string | null; run: (r: Row) => void }) {
  if (!r.runSafe) return <span />;
  return (
    <button className="play edge" disabled={!!why} title={why ?? `Run ${short(r.d.name)} now`} aria-label={`Run ${short(r.d.name)} now`}
      onClick={(e) => { e.stopPropagation(); run(r); }}>▶</button>
  );
}

/** A Board tie as the Kanban's label chip in the state's Board colour. */
const TieChip = ({ t }: { t: Tie }) => <span className="tie" title={t.note} style={{ "--tc": t.color } as CSSProperties}>{`⇢ ${t.text}`}</span>;

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

function Catalog({ data, rs, now, why, run, folded, toggle }: {
  data: DagData; rs: Row[]; now: number; why: (r: Row) => string | null; run: (r: Row) => void; folded: Set<string>; toggle: (k: string) => void;
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
                <div key={r.d.name} className={`trow p-${r.phase}${r.runSafe ? " startable" : ""}`}>
                  <Orb phase={r.phase} /><span className="nm" title={r.d.name}>{short(r.d.name)}</span><Strip r={r} />
                  <span className="last">{lastLine(r, now)}</span><span className="pool">{poolText(data.pools, r) || "—"}</span>
                  <span>{t ? <TieChip t={t} /> : <span className="none">—</span>}</span>
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

export function Dags({ data, post }: { data: DagData | null; post?: Post }) {
  const [q, setQ] = useState("");
  const [only, setOnly] = useState<Exclude<Phase, "queued"> | null>(null);
  const [dom, setDom] = useState<string | null>(null);
  const [menu, setMenu] = useState<"status" | "domain" | null>(null);
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<{ text: string; n: number } | null>(null);
  const [starting, setStarting] = useState<Set<string>>(new Set());
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

  const why = (r: Row) => (r.phase === "running" ? "Already running" : r.phase === "queued" ? "Already queued" : starting.has(r.d.name) ? "Starting…" : null);
  const run = async (r: Row) => {
    const name = r.d.name;
    setStarting((s) => new Set(s).add(name));
    const line = await startRun(name, post);
    setStarting((s) => { const n = new Set(s); n.delete(name); return n; });
    setToast((t) => ({ text: `${short(name)}: ${line}`, n: (t?.n ?? 0) + 1 }));
  };
  const rs = filterRows(all, { q, only, dom });
  // the Kanban's filter chip: a label, the chosen value, ▾; a press opens its menu
  const chip = (name: "status" | "domain", label: string, text: string | null) => (
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
          <input type="text" placeholder="filter by name, step or domain…" aria-label="Filter DAGs by name, step or domain" autoComplete="off" spellCheck={false} value={q}
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
        {(only || dom || q) && <button className="clear" onClick={() => { setOnly(null); setDom(null); setQ(""); }}>clear</button>}
        <span className="shown">{rs.length === all.length ? `${all.length} shown` : `${rs.length} of ${all.length} shown`}</span>
      </div>
      {rs.length ? <Catalog data={data} rs={rs} now={now} why={why} run={run} folded={folded} toggle={toggle} /> : <div className="none">No DAG matches the filters.</div>}
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
