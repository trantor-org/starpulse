// What the DAGs catalog and a DAG's modal both draw: the state dot, the step constellation (small in a row, large in the modal),
// the last-run line, the pool text and a Board tie's chip. Steps and links are drawn as the Star Map draws a DAG body's (boardDraw drawStars), in DAG_COLOR.
import type { CSSProperties, ReactNode } from "react";
import type { DagStep, Rerun } from "../../api";
import { ago, bigPlace, chartHeight, place, stepNote, took, type DagFacts, type Phase, type Row, type Tie } from "./dagsModel";
import { DAG_COLOR } from "../../render/draw";
import { orbiterLook } from "../../render/boardDraw";
import { useId } from "react";

/** A step's ink: its status colour, and the slate for a step with no run behind it, which the Star Map's near-black track colour leaves unreadable in a row. */
const ink = (status: string) => (status === "not_started" ? "var(--slate)" : DAG_COLOR[status] ?? DAG_COLOR.aborted);

/** A step as the Star Map draws a DAG body's steps (renderer drawStars): a ring in its status colour round a core dot, the row showing through, a little dimmer before it runs. */
export function StepStar({ x, y, r, status }: { x: number; y: number; r: number; status: string }) {
  const c = ink(status), idle = status === "not_started";
  return (
    <g className={`step s-${status}`}>
      <circle cx={x} cy={y} r={r} fill="none" stroke={c} strokeOpacity={idle ? 0.8 : 0.85} strokeWidth={1} className="ring" />
      <circle cx={x} cy={y} r={r * 0.34} fill={c} fillOpacity={idle ? 0.8 : 0.9} className="core" />
    </g>
  );
}

/** A dependency as the Star Map draws one inside a DAG body: a dashed curve shaded from one step's colour to the next, streaming toward the step that waits
 *  in the row the pointer, keyboard or a Recent line rests on and in the open DAG's chart (style.css); brighter and heavier while either end runs. */
function Link({ id, a, b, r, from, to }: { id: string; a: { x: number; y: number }; b: { x: number; y: number }; r: number; from: string; to: string }) {
  const hot = from === "running" || to === "running", dx = (b.x - a.x) / 2, [x0, x1] = [a.x + r, b.x - r];
  return (
    <>
      <linearGradient id={id} gradientUnits="userSpaceOnUse" x1={x0} y1={a.y} x2={x1} y2={b.y}>
        <stop offset="0" stopColor={ink(from)} /><stop offset="1" stopColor={ink(to)} />
      </linearGradient>
      <path d={`M${x0} ${a.y}C${a.x + dx} ${a.y} ${b.x - dx} ${b.y} ${x1} ${b.y}`} fill="none" stroke={`url(#${id})`} strokeOpacity={hot ? 0.8 : 0.55}
        strokeWidth={hot ? 1.9 : 1} strokeDasharray="1.8 4.2" className={hot ? "link hot" : "link"} />
    </>
  );
}

const PHASE_STATUS: Record<Phase, string> = { running: "running", queued: "queued", ok: "succeeded", failed: "failed", idle: "not_started" };

/** A DAG's state as the Star Map draws its orbiter (boardDraw `orbiterLook`): a ring round a core dot in the run's colour, the Spinner's quarter-arc
 *  turning while it runs, a dashed outer ring after a failed run, grey while it waits. */
export const Orb = ({ phase, big = false }: { phase: Phase; big?: boolean }) => {
  const look = orbiterLook(PHASE_STATUS[phase]), c = look.color, lit = look.spin || look.dashed;
  return (
    <i className={`orb o-${phase}${big ? " big" : ""}`} aria-hidden="true">
      <svg viewBox="-9 -9 18 18">
        <circle r={5} fill="none" stroke={c} strokeOpacity={lit ? 0.95 : 0.6} strokeWidth={1.3} className="ring" />
        <circle r={5 * (look.spin ? 0.45 : 0.4)} fill={c} fillOpacity={lit ? 0.95 : 0.7} className="core" />
        {look.spin && <path d="M 0 -8.5 A 8.5 8.5 0 0 1 8.5 0" fill="none" stroke={c} strokeOpacity={0.9} strokeWidth={1.4} className="spin" />}
        {look.dashed && <circle r={8.5} fill="none" stroke={c} strokeOpacity={0.7} strokeWidth={1} strokeDasharray="2 2" className="fail-ring" />}
      </svg>
    </i>
  );
};

/** A name cut to `n` characters with an ellipsis: the strip draws outside its box, so its text must fit. */
const fit = (t: string, n: number) => (t.length <= n ? t : `${t.slice(0, Math.max(1, Math.floor(n) - 1))}…`);
/** What one character of a step's name measures on screen: the page's text scale (`--fs`) times the chart's base size. The Admin sets the scale
 *  inline on `<html>`, which answers without the style recalculation `getComputedStyle` forces after every DOM change. */
export const labelPx = () => 6.1 * (Number(document.documentElement.style.getPropertyValue("--fs")) || 1);

/** The modal chart's size for a DAG: as wide as its steps and their names need, or as the steps spread when nothing squeezes them, and as high as
 *  its widest column. The modal's own width follows it. */
export function chartBox(r: Row) {
  const px = labelPx(), least = bigPlace(r.d.steps, 0, 100, px), spread = bigPlace(r.d.steps, 1e6, 100, px);
  return { w: Math.max(least.span, spread.span), h: chartHeight(least.wide) };
}

/** How many past runs a step's history strip has room for. */
const SLOTS = 5;

/** A DAG's step history: one line per step, its last runs as a strip of ticks oldest to newest in each run's status colour, an empty slot for a run not made. */
export function StepHistory({ steps, rerun }: { steps: DagStep[]; rerun: Rerun | null }) {
  return (
    <ul className="hist">
      {steps.map((s) => {
        const runs = [...s.last].reverse(), note = stepNote(s, rerun);
        return (
          <li key={s.name}>
            <span className="nm">{s.name}</span>
            <span className="runs" role="img" aria-label={runs.length ? `last runs, oldest first: ${runs.join(", ").replace(/_/g, " ")}` : "no runs yet"}>
              {Array.from({ length: SLOTS }, (_, i) => {
                const v = runs[i - (SLOTS - runs.length)];
                return <i key={i} className={v ? `s-${v}` : ""} title={v?.replace("_", " ")} />;
              })}
            </span>
            {note && <span className="note k">{note}</span>}
          </li>
        );
      })}
    </ul>
  );
}

/** A DAG's steps as a constellation: one star per step in its status colour, joined by its dependencies; the running step burns
 *  and an agent step is ringed. `big` is the modal's chart: larger stars, each named, a fan folded into sub-columns. */
export function Strip({ r, w = 220, h = 20, big = false }: { r: Row; w?: number; h?: number; big?: boolean }) {
  const st = r.d.steps;
  // a folded fan's sub-columns sit a small star's width and a gap apart, and a strip whose column stacks draws small stars
  const p = big ? bigPlace(st, w, h - 12, labelPx()) : place(st, w, h, 7, 3, 8, 34, Math.min(7, (h - 6) / 2));
  const rr = big ? 6 : st.length > 9 || p.wide > 1 ? 3 : 4, uid = useId().replace(/:/g, "");
  const at = (n: string) => r.steps[n] ?? "not_started";
  return (
    <svg className={`dstrip${big ? " big" : ""}`} width={big ? w : "100%"} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMinYMid meet" aria-hidden={!big}>
      {st.flatMap((s) => s.depends.filter((d) => p.at[d]).map((d) => (
        <Link key={d + ">" + s.name} id={`${uid}-${d}-${s.name}`.replace(/[^\w-]/g, "_")} a={p.at[d]} b={p.at[s.name]} r={rr} from={at(d)} to={at(s.name)} />
      )))}
      {st.map((s) => {
        const v = at(s.name), { x, y } = p.at[s.name];
        return (
          <g key={s.name} className={`sd s-${v}`}>
            <StepStar x={x} y={y} r={rr} status={v} />
            {s.kind === "agent" && <circle cx={x} cy={y} r={rr + (big ? 4 : 2.5)} fill="none" stroke="var(--agent)" strokeWidth={big ? 1 : 0.7} />}
            {big && <text x={x} y={y + (p.up(s.name) ? -14 : 22)} className={v === "running" ? "hot" : undefined}>{s.name}</text>}
            {big && <title>{`${s.name}: ${v.replace("_", " ")}${s.kind ? ` (${s.kind} step)` : ""}`}</title>}
          </g>
        );
      })}
      {!big && st.length === 1 && <text x={16} y={h / 2 + 3.5} className="one">{fit(st[0].name, (w - 22) / (labelPx() * 0.88))}</text>}
    </svg>
  );
}

/** What a row's last-run cell says: the step a run is in and for how long, the step a run failed at, or when the last run ended and how long it took. */
export function lastLine(r: Row, now: number): ReactNode {
  if (r.phase === "running") return <><b className="hot">{r.step || "starting"}</b>{r.startedAt ? ` · ${took(r.startedAt, now)}` : ""}</>;
  if (r.phase === "queued") return <b className="q">queued</b>;
  if (r.phase === "idle") return "never run";
  if (r.phase === "failed") {
    const at = Object.entries(r.steps).find(([, v]) => v === "failed" || v === "aborted")?.[0];
    return <><span className="bad">{r.d.status === "aborted" ? "aborted" : "failed"}{at ? ` at ${at}` : ""}</span>{r.finishedAt ? ` · ${ago(now, r.finishedAt)}` : ""}</>;
  }
  if (!r.finishedAt) return "ran";
  return <>{ago(now, r.finishedAt)}{r.startedAt ? ` · ${took(r.startedAt, r.finishedAt)}` : ""}</>;
}

/** A Processing row's Elapsed and Progress cells: how long the run has gone, and how many steps are done and running. */
export function RunCells({ r, now }: { r: Row; now: number }) {
  const states = Object.values(r.steps), done = states.filter((v) => v === "succeeded" || v === "skipped").length, live = states.filter((v) => v === "running").length;
  return (
    <>
      <span className="num">{r.phase === "running" && r.startedAt ? took(r.startedAt, now) : <span className="k">waiting</span>}</span>
      <span className="last">{r.phase === "queued" ? <b className="q">queued</b> : <><b className="hot">{done}/{states.length} done</b>{live ? ` · ${live} running` : ""}</>}</span>
    </>
  );
}

/** An Idle row's Last run, Runs/week and Duration cells: how the last run ended and when, the week's runs, and the p95 run time with its failure share (red from 10%). */
export function IdleCells({ r, f, now }: { r: Row; f: DagFacts | undefined; now: number }) {
  const when = r.finishedAt ? ` ${ago(now, r.finishedAt)}` : "";
  const fail = f?.failureShare == null ? null : Math.round(f.failureShare * 100);
  return (
    <>
      <span className="last">{r.phase === "idle" ? <span className="none">never run</span>
        : r.phase === "failed" ? <><span className="bad">{r.d.status === "aborted" ? "aborted" : "failed"}</span>{when}</> : <><b>succeeded</b>{when}</>}</span>
      <span className="num">{f?.runs == null ? "—" : f.runs.toLocaleString()}</span>
      <span className={`num${fail !== null && fail >= 10 ? " bad" : ""}`}>{f?.p95Seconds == null ? "—" : `p95 ${took(0, f.p95Seconds)}`}{fail !== null && <span className="k"> · {fail}% fail</span>}</span>
    </>
  );
}

/** Opens a tie's Ledger on the Star Map, or null when the tie names no transition that has one. */
export type LedgerGo = (ev: string | undefined) => (() => void) | null;

/** A link that runs `go` instead of following its address; the click stops here, so a row's own click (its modal) never hears it. */
const LedgerLink = ({ go, className, title, style, children }: { go: () => void; className: string; title?: string; style?: CSSProperties; children: ReactNode }) => (
  <a className={className} href="#" title={title} style={style} onClick={(e) => { e.preventDefault(); e.stopPropagation(); go(); }}>{children}</a>
);

/** A Board tie as the Kanban's label chip in the state's Board colour; `label` replaces its text where the modal names the kind. A tie whose
 *  transition has a Ledger (`go`) is a link to it. */
export function TieChip({ t, label, ledger }: { t: Tie; label?: string; ledger?: LedgerGo }) {
  const go = ledger?.(t.ev), text = `⇢ ${label ?? t.text}`, style = { "--tc": t.color } as CSSProperties;
  return go ? <LedgerLink go={go} className="tie" title={t.note} style={style}>{text}</LedgerLink> : <span className="tie" title={t.note} style={style}>{text}</span>;
}

/** The modal's "open the <EVENT> Ledger ↗" link under a tie, in the modal's violet; nothing for a tie with no Ledger. */
export const LedgerNote = ({ t, ledger }: { t: Tie; ledger?: LedgerGo }) => {
  const go = ledger?.(t.ev);
  return go ? <LedgerLink go={go} className="lgnote">open the {t.ev} Ledger ↗</LedgerLink> : null;
};
