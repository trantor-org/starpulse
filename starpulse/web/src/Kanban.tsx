// The Kanban view: the Board's open tasks as six columns of milestone buckets, with drag and modal moves. The model is kanban.ts and move.ts; this draws them.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import type { HudState } from "./hud";
import {
  COLUMNS, applySuggestion, assigneeOptions, clearFilters, filtersActive, hideMilestone, hideTask, labelSuggestions, layout, milestoneOptions, show, showAll, toggleFold,
  type KanbanTask, type Option, type Prefs,
} from "./kanban";
import { loadPrefs, savePrefs, withoutFilters } from "./kanbanPrefs";
import { codeParts, place, targets, type MoveStore, type Refusal, type Target } from "./move";
import { browserStorage } from "./nav";
import type { Pull } from "./types";

/** A milestone's header: the key the snapshot carries, or the bucket for tasks with none. */
const milestoneName = (milestone: string) => milestone || "No milestone";
/** A machine event this recent still pulses on its card, in seconds. */
const HOT_S = 120;

const ago = (seconds: number) => {
  const m = Math.max(0, Math.round(seconds / 60));
  return m < 1 ? "now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;
};
const profileColor = (a: string) => (/deep/.test(a) ? "#a78bfa" : /standard/.test(a) ? "#67e8f9" : /fast/.test(a) ? "#fbbf24" : "#94a3b8");
const shortProfile = (a: string) => a.replace(/^@agent-/, "").replace(/^@/, "");
const checksClass = (p: Pull) => (p.merged ? "merged" : p.checks === "failing" ? "fail" : p.checks);

function PullChip({ pulls }: { pulls: Pull[] }) {
  const p = pulls[0];
  if (!p) return null;
  return (
    <span className={`pr ${checksClass(p)}`} title={`${p.merged ? "merged" : `checks ${p.checks}`}${p.threads ? `, ${p.threads} open review threads` : ""}${p.stale ? " (last read failed)" : ""}`}>
      <i />#{p.number}
      {p.threads > 0 && <span className="th"> ⌁{p.threads}</span>}
      {pulls.length > 1 && ` +${pulls.length - 1}`}
    </span>
  );
}

/** What a card shows beyond its task: a move still being saved, a refusal, or that it is the one lifted. */
interface Marks {
  saving?: boolean;
  refusal?: Refusal;
  lifted?: boolean;
}

const Reason = ({ text }: { text: string }) => (
  <>{codeParts(text).map((p, i) => (p.code ? <code key={i}>{p.text}</code> : p.text))}</>
);

/** The writer's or the guard's refusal, with the skill that satisfies it, on the card that was refused. */
function RefusalNote({ refusal, names, dismiss }: { refusal: Refusal; names: Record<string, string>; dismiss: () => void }) {
  return (
    <div className="refusal">
      <div className="k">Move to {names[refusal.to] ?? refusal.to} refused · stayed in {names[refusal.from] ?? refusal.from}</div>
      <Reason text={refusal.reason} />
      <div className="via">
        {refusal.skill && <>Satisfied by&nbsp;<span className="skill">{refusal.skill}</span></>}
        <button className="dismiss" onClick={(e) => { e.stopPropagation(); dismiss(); }} onPointerDown={(e) => e.stopPropagation()}>dismiss</button>
      </div>
    </div>
  );
}

function Card({ task, now, marks, names, onOpen, onPress, dismiss, style }: {
  task: KanbanTask; now: number; marks: Marks; names: Record<string, string>; onOpen: () => void; onPress?: (e: React.PointerEvent<HTMLDivElement>) => void;
  dismiss: () => void; style?: CSSProperties;
}) {
  const labels = task.labels.filter((l) => !/^kind-|^agent-resolvable$/.test(l)).slice(0, 3);
  const live = task.live;
  const cls = ["card", marks.saving && "saving", marks.refusal && "bad", marks.lifted && "ghost"].filter(Boolean).join(" ");
  return (
    <div className={cls} role="button" tabIndex={0} data-id={task.id} style={style} onClick={onOpen} onPointerDown={onPress}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen())}>
      <div className="top"><span className="id">{task.id}</span><PullChip pulls={task.prs} /></div>
      <div className="t">{task.title}</div>
      {live && (
        <div className={`mach${now - live.at < HOT_S ? " hot" : ""}`}>
          <span className="p" /><b>{live.machine}</b><span className="s">· {live.state.replace(/_/g, " ")}</span><span className="ago">{ago(now - live.at)}</span>
        </div>
      )}
      <div className="foot">
        {labels.map((l) => (
          <span key={l} className={`lab${l === "needs-human" ? " nh" : /^size-/.test(l) ? " sz" : ""}`}>{/^size-/.test(l) ? `${l.slice(5)}pt` : l}</span>
        ))}
        {task.openDeps > 0 && <span className="dep" title="open dependencies">⧗{task.openDeps}</span>}
        {task.assignee ? <span className="who"><i style={{ background: profileColor(task.assignee) }} />{shortProfile(task.assignee)}</span> : <span className="who">unassigned</span>}
      </div>
      {marks.refusal && <RefusalNote refusal={marks.refusal} names={names} dismiss={dismiss} />}
    </div>
  );
}

function Modal({ task, names, marks, now, close, hide, constellation, move, dismiss }: {
  task: KanbanTask; names: Record<string, string>; marks: Marks; now: number; close: () => void; hide: () => void; constellation: () => void;
  move: (to: string) => void; dismiss: () => void;
}) {
  const lane = names[task.lane] ?? task.lane;
  // the columns the Board machine offers, each as the drag would: an allowed move goes at once, a guarded one is refused on the card with the guard's reason
  const offered = COLUMNS.filter((c) => c in task.moves);
  const deps = task.dependencies.map((d) => <span key={d}>{d}</span>);
  return (
    <div id="kbm" onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="modal" role="dialog" aria-label={task.id}>
        <button className="x" onClick={close} aria-label="Close">✕</button>
        <h2>{task.title}</h2>
        <div className="k">{task.id} · {lane}{marks.saving ? " · saving" : ""}</div>
        <table><tbody>
          <tr><td>profile</td><td>{task.assignee || "unassigned"}</td></tr>
          <tr><td>labels</td><td>{task.labels.join(", ") || "—"}</td></tr>
          <tr><td>milestone</td><td>{task.milestone || "—"}</td></tr>
          <tr><td>depends on</td><td>{deps.length ? deps.flatMap((d, i) => (i ? [", ", d] : [d])) : "—"}</td></tr>
          <tr><td>pull requests</td><td>{task.prs.length ? task.prs.map((p) => (
            <div key={p.number}><a href={p.url} target="_blank" rel="noopener">#{p.number}</a> <span className="k">{p.merged ? "merged" : p.checks}{p.threads ? `, ${p.threads} open threads` : ""}</span></div>
          )) : "—"}</td></tr>
          <tr><td>machine</td><td>{task.live ? `${task.live.machine} · ${task.live.state} · ${ago(now - task.live.at)} ago` : "—"}</td></tr>
        </tbody></table>
        <div className="k moveto">Move to</div>
        <div className="moves">
          {offered.length ? offered.map((c) => {
            const v = task.moves[c];
            return <button key={c} className={v.allowed ? "ok" : "guard"} title={v.allowed ? undefined : v.reason} disabled={marks.saving} onClick={() => move(c)}>→ {names[c] ?? c}</button>;
          }) : <span className="k">no moves from here</span>}
        </div>
        {marks.refusal && <RefusalNote refusal={marks.refusal} names={names} dismiss={dismiss} />}
        <div className="desc">{task.description.split("\n## ")[0] || "(no description)"}</div>
        <div className="mfoot">
          <a onClick={constellation} href="/">Open in Constellation ↗</a>
          <span className="mright"><button className="hidebtn" onClick={hide}>Hide task</button></span>
        </div>
      </div>
    </div>
  );
}

/** The Hidden chip's menu: what is hidden, each to show back, or all at once. */
function HiddenMenu({ prefs, tasks, set, close }: { prefs: Prefs; tasks: KanbanTask[]; set: (p: Prefs) => void; close: () => void }) {
  const title = (id: string) => tasks.find((t) => t.id === id)?.title ?? "";
  const count = (m: string) => tasks.filter((t) => t.milestone === m).length;
  return (
    <>
      <div className="scrim" onClick={close} />
      <div className="menu" role="menu">
        {prefs.hiddenMilestones.size > 0 && <div className="hd">Hidden milestones</div>}
        {[...prefs.hiddenMilestones].map((m) => (
          <button key={m} role="menuitem" onClick={() => set(show(prefs, "milestone", m))}>{milestoneName(m)}<span>{count(m)} · show</span></button>
        ))}
        {prefs.hiddenTasks.size > 0 && <div className="hd">Hidden tasks</div>}
        {[...prefs.hiddenTasks].map((id) => (
          <button key={id} role="menuitem" onClick={() => set(show(prefs, "task", id))}>{id} <em className="tt">{title(id)}</em><span>show</span></button>
        ))}
        <button role="menuitem" className="all" onClick={() => { set(showAll(prefs)); close(); }}>Show all</button>
      </div>
    </>
  );
}

type MenuName = "assignee" | "milestone" | "hidden";

/** One of the Assignee or Milestone menus: each value with its count; the chosen one is picked again to clear it. */
function ChoiceMenu({ title, options, value, name, set, close }: {
  title: string; options: Option[]; value: string | null; name: (v: string) => string; set: (v: string | null) => void; close: () => void;
}) {
  return (
    <>
      <div className="scrim" onClick={close} />
      <div className="menu" role="menu">
        <div className="hd">{title}</div>
        {options.map((o) => (
          <button key={o.value} role="menuitemradio" aria-checked={o.value === value} className={o.value === value ? "on" : undefined}
            onClick={() => { set(o.value === value ? null : o.value); close(); }}>{name(o.value)}<span>{o.count}</span></button>
        ))}
      </div>
    </>
  );
}

/** What a press on a card and the pointer after it are doing: nothing yet (a click), or carrying the card to a column. */
interface Press {
  task: KanbanTask;
  kinds: Record<string, Target>;
  x: number;
  y: number;
  dx: number;
  dy: number;
  w: number;
  lifted: boolean;
}
/** Pixels a press travels before it lifts the card instead of opening it. */
const LIFT_PX = 5;

export function Kanban({ hud, moves, constellation }: { hud: HudState; moves: MoveStore; constellation: (lane: string) => void }) {
  const [storage] = useState(browserStorage);
  const [prefs, setPrefs] = useState<Prefs>(() => loadPrefs(storage, location.search));
  const [open, setOpen] = useState<string | null>(null);
  const [menu, setMenu] = useState<MenuName | null>(null);
  const [typing, setTyping] = useState(false);
  const [pick, setPick] = useState(0);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [lift, setLift] = useState<{ id: string; kinds: Record<string, Target>; over: string | null; w: number } | null>(null);
  const [bounced, setBounced] = useState<string | null>(null);
  const moved = useSyncExternalStore(moves.subscribe, moves.get);
  const ghost = useRef<HTMLDivElement>(null);
  const press = useRef<Press | null>(null);
  const dropRect = useRef<{ id: string; rect: DOMRect } | null>(null);
  const clickEnds = useRef(false);
  // the "ago" stamps keep counting between snapshots
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 30_000);
    return () => clearInterval(timer);
  }, []);
  // what the operator chose is kept for the next visit; a deep link's filters are the first thing kept
  useEffect(() => savePrefs(storage, prefs), [storage, prefs]);
  // once the view has taken a deep link's filters they leave the address, or a reload would undo what was changed since
  useEffect(() => {
    const clean = withoutFilters(location.search);
    if (clean !== location.search) history.replaceState(null, "", `${location.pathname}${clean}`);
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(null);
      setMenu(null);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
  // a streamed board ends the moves and refusals it has overtaken
  useEffect(() => moves.sync(hud.cards), [moves, hud.cards]);
  useEffect(() => {
    document.body.classList.toggle("dragging", lift !== null);
    return () => document.body.classList.remove("dragging");
  }, [lift]);
  const cards = useMemo(() => place(hud.cards, moved), [hud.cards, moved]);
  const view = useMemo(() => layout(cards, hud.names, prefs), [cards, hud.names, prefs]);
  const task = open ? cards.find((t) => t.id === open) : undefined;
  const marksOf = (id: string): Marks => ({ saving: moved.pending[id]?.saving, refusal: moved.refused[id] });
  const suggestions = useMemo(() => labelSuggestions(cards, prefs.query), [cards, prefs.query]);
  const at = Math.min(pick, suggestions.length - 1);
  const assignees = useMemo(() => assigneeOptions(cards), [cards]);
  const milestones = useMemo(() => milestoneOptions(cards), [cards]);
  const choose = (label: string) => {
    setPrefs((p) => ({ ...p, query: applySuggestion(p.query, label) }));
    setPick(0);
  };
  const onSearchKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") e.currentTarget.blur();
    if (!typing || suggestions.length === 0) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setPick((at + (e.key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(suggestions[at].label);
    }
  };
  const chip = (name: MenuName, label: string, value: string | null, text: string) => (
    <span className={`fchip${value !== null ? " set" : ""}`} role="button" tabIndex={0} aria-haspopup="menu" aria-expanded={menu === name}
      onClick={() => setMenu((m) => (m === name ? null : name))} onKeyDown={(e) => e.key === "Enter" && setMenu((m) => (m === name ? null : name))}>
      {label}{value !== null && <>: <b>{text}</b></>} ▾
    </span>
  );

  // a landed card flies from where it was dropped to its place in the target column
  useLayoutEffect(() => {
    const landed = dropRect.current;
    if (!landed) return;
    dropRect.current = null;
    const el = document.querySelector<HTMLElement>(`#cols .card[data-id="${landed.id}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "nearest" });
    const at = el.getBoundingClientRect();
    el.style.transform = `translate(${landed.rect.left - at.left}px,${landed.rect.top - at.top}px)`;
    if (!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      el.style.animation = "kb-arrive 2.4s ease-out";
      el.addEventListener("animationend", (e) => { if (e.animationName === "kb-arrive") el.style.animation = ""; });
    }
    requestAnimationFrame(() => requestAnimationFrame(() => {
      el.style.transition = "transform .18s ease-out";
      el.style.transform = "";
    }));
  }, [moved.pending]);
  useLayoutEffect(() => {
    if (!lift || !ghost.current || !press.current) return;
    const p = press.current;
    ghost.current.style.left = `${p.x - p.dx}px`;
    ghost.current.style.top = `${p.y - p.dy}px`;
  }, [lift]);

  const begin = (t: KanbanTask) => (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest(".refusal")) return;
    const box = e.currentTarget.getBoundingClientRect();
    const p: Press = { task: t, kinds: targets(t, COLUMNS), x: e.clientX, y: e.clientY, dx: e.clientX - box.left, dy: e.clientY - box.top, w: box.width, lifted: false };
    press.current = p;
    const overOf = (x: number, y: number) => document.elementFromPoint(x, y)?.closest<HTMLElement>(".col")?.dataset.lane ?? null;
    const end = () => {
      removeEventListener("pointermove", onMove);
      removeEventListener("pointerup", onUp);
      removeEventListener("pointercancel", cancel);
      removeEventListener("keydown", onKey);
      press.current = null;
    };
    const onMove = (m: PointerEvent) => {
      p.x = m.clientX;
      p.y = m.clientY;
      if (!p.lifted) {
        if (Math.hypot(m.clientX - e.clientX, m.clientY - e.clientY) < LIFT_PX) return;
        p.lifted = true;
        setLift({ id: t.id, kinds: p.kinds, over: null, w: p.w });
        setOpen(null);
        setMenu(null);
        return;
      }
      if (ghost.current) {
        ghost.current.style.left = `${m.clientX - p.dx}px`;
        ghost.current.style.top = `${m.clientY - p.dy}px`;
      }
      const over = overOf(m.clientX, m.clientY);
      setLift((l) => (l && l.over !== over ? { ...l, over } : l));
    };
    const onUp = (u: PointerEvent) => {
      const was = p.lifted, rect = ghost.current?.getBoundingClientRect();
      end();
      if (!was) return;
      // the click that follows a drag must not open the card
      clickEnds.current = true;
      setTimeout(() => (clickEnds.current = false));
      setLift(null);
      const to = overOf(u.clientX, u.clientY);
      const kind = to ? p.kinds[to]?.kind : undefined;
      if (to && (kind === "ok" || kind === "guard")) {
        if (rect) dropRect.current = { id: t.id, rect };
        void moves.drop(t, to);
      } else {
        setBounced(t.id);
        setTimeout(() => setBounced(null), 650);
      }
    };
    const cancel = () => {
      end();
      setLift(null);
    };
    const onKey = (k: KeyboardEvent) => k.key === "Escape" && cancel();
    addEventListener("pointermove", onMove);
    addEventListener("pointerup", onUp);
    addEventListener("pointercancel", cancel);
    addEventListener("keydown", onKey);
  };
  const lifted = lift ? cards.find((t) => t.id === lift.id) : undefined;
  const openCard = (id: string) => () => !clickEnds.current && setOpen(id);
  return (
    <main id="kb">
      <header><span className="title">Kanban</span><span className="count">{view.open} open · {view.done} done</span></header>
      <div className="filters">
        <div className="fw">
          <input id="kbq" type="text" value={prefs.query} placeholder="filter by id, title or label…" aria-label="Filter tasks by id, title or label" autoComplete="off" spellCheck={false}
            onChange={(e) => { setPrefs((p) => ({ ...p, query: e.target.value })); setPick(0); }}
            onFocus={() => setTyping(true)} onBlur={() => setTyping(false)} onKeyDown={onSearchKey} />
          {typing && suggestions.length > 0 && (
            <div className="menu sug" role="listbox" aria-label="Labels">
              <div className="hd">Filter by label</div>
              {suggestions.map((s, i) => (
                <button key={s.label} role="option" aria-selected={i === at} className={i === at ? "on" : undefined}
                  onMouseDown={(e) => e.preventDefault()} onClick={() => choose(s.label)}>{s.label}<span>{s.count}</span></button>
              ))}
            </div>
          )}
        </div>
        <div className="fw">
          {chip("assignee", "Assignee", prefs.assignee, prefs.assignee ? shortProfile(prefs.assignee) : "unassigned")}
          {menu === "assignee" && (
            <ChoiceMenu title="Assignee" options={assignees} value={prefs.assignee} name={(v) => (v ? shortProfile(v) : "unassigned")}
              set={(assignee) => setPrefs((p) => ({ ...p, assignee }))} close={() => setMenu(null)} />
          )}
        </div>
        <div className="fw">
          {chip("milestone", "Milestone", prefs.milestone, milestoneName(prefs.milestone ?? ""))}
          {menu === "milestone" && (
            <ChoiceMenu title="Milestone" options={milestones} value={prefs.milestone} name={milestoneName}
              set={(milestone) => setPrefs((p) => ({ ...p, milestone }))} close={() => setMenu(null)} />
          )}
        </div>
        {filtersActive(prefs) && <button className="clear" onClick={() => setPrefs(clearFilters)}>clear</button>}
        {view.hidden > 0 && (
          <div className="fw">
            <span className="fchip set" role="button" tabIndex={0} aria-haspopup="menu" aria-expanded={menu === "hidden"}
              onClick={() => setMenu((m) => (m === "hidden" ? null : "hidden"))} onKeyDown={(e) => e.key === "Enter" && setMenu((m) => (m === "hidden" ? null : "hidden"))}>
              Hidden: <b>{view.hidden}</b> ▾
            </span>
            {menu === "hidden" && <HiddenMenu prefs={prefs} tasks={cards} set={setPrefs} close={() => setMenu(null)} />}
          </div>
        )}
        <span className="shown">{view.shown} of {view.total} tasks</span>
      </div>
      <div id="cols">
        {view.columns.map((col) => {
          const target = lift?.kinds[col.id];
          const colCls = ["col", target && target.kind !== "here" && target.kind, lift?.over === col.id && target?.kind !== "here" && "over"].filter(Boolean).join(" ");
          return (
            <section key={col.id} className={colCls} data-lane={col.id}>
              <h2><span className="g" />{col.name}<span className="c">{col.count}</span>
                {target && target.kind !== "here" && (
                  <span className="hint">{target.kind === "ok" ? "drop" : target.kind === "guard" ? `guarded · ${target.skill || "refused"}` : "no transition"}</span>
                )}
              </h2>
              {target?.kind === "guard" && <div className="why"><Reason text={target.reason} /></div>}
              <div className="body">
                {col.buckets.length === 0 && <div className="empty">no tasks</div>}
                {col.buckets.map((b) => (
                  <div key={b.milestone} className={`bucket${b.folded ? " folded" : ""}`}>
                    <div className="bh" role="button" tabIndex={0} title={milestoneName(b.milestone)} aria-expanded={!b.folded}
                      onClick={() => setPrefs((p) => toggleFold(p, b.milestone))} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setPrefs((p) => toggleFold(p, b.milestone)))}>
                      <span className="tw">▾</span><span className="bn">{milestoneName(b.milestone)}</span><span className="c">{b.tasks.length}</span>
                      <button className="hide" title="Hide this milestone" onClick={(e) => { e.stopPropagation(); setPrefs((p) => hideMilestone(p, b.milestone)); }}>hide</button>
                    </div>
                    {!b.folded && b.tasks.map((t) => (
                      <Card key={t.id} task={t} now={now} names={hud.names} marks={{ ...marksOf(t.id), lifted: lift?.id === t.id }}
                        style={bounced === t.id ? { animation: "kb-shake .65s" } : undefined}
                        onOpen={openCard(t.id)} onPress={begin(t)} dismiss={() => moves.dismiss(t.id)} />
                    ))}
                  </div>
                ))}
              </div>
            </section>
          );
        })}
      </div>
      {lifted && (
        <div ref={ghost} className="lift">
          <Card task={lifted} now={now} names={hud.names} marks={{}} onOpen={() => {}} dismiss={() => {}} style={{ width: lift?.w }} />
        </div>
      )}
      {task && (
        <Modal task={task} names={hud.names} marks={marksOf(task.id)} now={now} close={() => setOpen(null)}
          hide={() => { setPrefs((p) => hideTask(p, task.id)); setOpen(null); }} constellation={() => constellation(task.lane)}
          move={(to) => void moves.drop(task, to)} dismiss={() => moves.dismiss(task.id)} />
      )}
    </main>
  );
}
