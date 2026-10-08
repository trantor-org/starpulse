// What the DAGs catalog and a DAG's modal both draw: the state dot, the step constellation (small in a row, large in the modal),
// the last-run line, the pool text and a Board tie's chip. Steps and links are drawn as the Star Map draws a DAG body's (renderer drawStars), in DAG_COLOR.
import type { CSSProperties, ReactNode } from "react";
import { ago, bigPlace, chartHeight, place, short, took, type Phase, type Row, type Tie } from "./dags";
import { DAG_COLOR } from "../../render/renderer";
import { useId } from "react";
import type { Pool } from "../../api";

/** A step as the Star Map draws a DAG body's steps (renderer drawStars): a dark disc ringed in its status colour round a core dot, dimmer before it runs. */
export function StepStar({ x, y, r, status }: { x: number; y: number; r: number; status: string }) {
  const c = DAG_COLOR[status] ?? DAG_COLOR.aborted, idle = status === "not_started";
  return (
    <g className={`step s-${status}`}>
      <circle cx={x} cy={y} r={r} fill="var(--bg0)" stroke={c} strokeOpacity={idle ? 0.45 : 0.85} strokeWidth={1} className="ring" />
      <circle cx={x} cy={y} r={r * 0.34} fill={c} fillOpacity={idle ? 0.45 : 0.9} className="core" />
    </g>
  );
}

/** A dependency as the Star Map draws one inside a DAG body: a dashed curve shaded from one step's colour to the next, streaming toward the step that waits;
 *  brighter and heavier while either end runs. */
function Link({ id, a, b, r, from, to }: { id: string; a: { x: number; y: number }; b: { x: number; y: number }; r: number; from: string; to: string }) {
  const hot = from === "running" || to === "running", dx = (b.x - a.x) / 2, [x0, x1] = [a.x + r, b.x - r];
  return (
    <>
      <linearGradient id={id} gradientUnits="userSpaceOnUse" x1={x0} y1={a.y} x2={x1} y2={b.y}>
        <stop offset="0" stopColor={DAG_COLOR[from] ?? DAG_COLOR.aborted} /><stop offset="1" stopColor={DAG_COLOR[to] ?? DAG_COLOR.aborted} />
      </linearGradient>
      <path d={`M${x0} ${a.y}C${a.x + dx} ${a.y} ${b.x - dx} ${b.y} ${x1} ${b.y}`} fill="none" stroke={`url(#${id})`} strokeOpacity={hot ? 0.8 : 0.42}
        strokeWidth={hot ? 1.9 : 1} strokeDasharray="1.8 4.2" className={hot ? "link hot" : "link"} />
    </>
  );
}

const PHASE_STATUS: Record<Phase, string> = { running: "running", queued: "queued", ok: "succeeded", failed: "failed", idle: "not_started" };

/** A DAG's state as one of its steps would be drawn in that state. */
export const Orb = ({ phase, big = false }: { phase: Phase; big?: boolean }) => (
  <i className={`orb o-${phase}${big ? " big" : ""}`} aria-hidden="true">
    <svg viewBox="-6 -6 12 12"><StepStar x={0} y={0} r={5} status={PHASE_STATUS[phase]} /></svg>
  </i>
);

/** A name cut to `n` characters with an ellipsis: the strip draws outside its box, so its text must fit. */
const fit = (t: string, n: number) => (t.length <= n ? t : `${t.slice(0, Math.max(1, Math.floor(n) - 1))}…`);
/** What one character of a step's name measures on screen: the page's text scale (`--fs`) times the chart's base size. The Admin sets the scale
 *  inline on `<html>`, which answers without the style recalculation `getComputedStyle` forces after every DOM change. */
export const labelPx = () => 6.1 * (Number(document.documentElement.style.getPropertyValue("--fs")) || 1);

/** The modal chart's size for a DAG: as wide as its steps and their names need (at least `min`), as high as its widest column. */
export function chartBox(r: Row, min = 924) {
  const fan = bigPlace(r.d.steps, 0, 100, labelPx());
  return { w: Math.max(min, fan.span), h: chartHeight(fan.wide) };
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

export const poolText = (pools: Pool[], r: Row) => {
  const p = pools.find((x) => x.name === r.d.pool);
  return p ? `${short(p.name)} ${p.running}/${p.cap}${p.queued ? ` +${p.queued}` : ""}` : "";
};

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
