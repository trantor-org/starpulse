// The Kanban view: the Board's open tasks as six columns of milestone buckets, with drag and modal moves and sessions started from a card.
// The model is kanban.ts, move.ts and start.ts; this draws them.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import { withoutArchived } from "./archive";
import { ArchiveDialog } from "./ArchiveConfirm";
import type { HudState } from "./hud";
import {
  COLUMNS, applySuggestion, applyTaskRecord, assigneeOptions, clearFilters, filtersActive, hideMilestone, hideTask, labelSuggestions, layout, milestoneOptions, show, showAll, toggleFold,
  type KanbanTask, type Option, type Prefs,
} from "./kanban";
import { linkedTask, loadPrefs, savePrefs, withoutFilters } from "./kanbanPrefs";
import { codeParts, place, targets, type MoveStore, type Refusal, type Target } from "./move";
import { browserStorage } from "./nav";
import {
  canDrag, dropAsks, placeClaims, profileOf, runsOn, startLane, startable,
  type Asking, type Claiming, type Failed, type Harnesses, type Pick, type StartStore,
} from "./start";
import { TaskView } from "./TaskView";
import { fetchRecord, type TaskRecord } from "./taskView";
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

/** What a card shows beyond its task: a move still being saved, a refusal, that it is the one lifted, a session it waits on, or a start that failed. */
interface Marks {
  saving?: boolean;
  refusal?: Refusal;
  lifted?: boolean;
  claim?: Claiming;
  failed?: Failed;
}
const stop = (e: React.SyntheticEvent) => e.stopPropagation();

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

/** A session start that failed, or the agent's claim the writer refused, on the card it returned; a refused claim's session stays open. */
function StartNote({ id, failed, names, dismiss }: { id: string; failed: Failed; names: Record<string, string>; dismiss: () => void }) {
  const lane = names[failed.from] ?? failed.from;
  return (
    <div className="refusal">
      <div className="k">{failed.refused ? "Claim refused" : "Session did not start"} · back in {lane}</div>
      {failed.refused ? <>The session's agent could not claim {id}: <Reason text={failed.reason.replace(/\.$/, "")} />. The session stays open.</> : <Reason text={failed.reason} />}
      <div className="via">
        {failed.url && <a href={failed.url} target="_blank" rel="noopener" onClick={stop} onPointerDown={stop}>Open session ↗</a>}
        <button className="dismiss" onClick={(e) => { e.stopPropagation(); dismiss(); }} onPointerDown={stop}>dismiss</button>
      </div>
    </div>
  );
}

/** A task card; compact keeps the id, pull request, title and machine line and drops the footer of labels, dependencies and profile. */
export function Card({ task, now, marks, names, compact = false, onOpen, onPress, onPlay, dismiss, dismissStart, style }: {
  task: KanbanTask; now: number; marks: Marks; names: Record<string, string>; compact?: boolean; onOpen: () => void; onPress?: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPlay?: () => void; dismiss: () => void; dismissStart?: () => void; style?: CSSProperties;
}) {
  const labels = task.labels.filter((l) => !/^kind-|^agent-resolvable$/.test(l)).slice(0, 3);
  const live = task.live, claim = marks.claim;
  const cls = ["card", compact && "compact", marks.saving && "saving", (marks.refusal || marks.failed) && "bad", marks.lifted && "ghost", claim && "claiming"].filter(Boolean).join(" ");
  const guard = task.moves.in_progress?.allowed === false ? task.moves.in_progress.reason : "";
  return (
    <div className={cls} role="button" tabIndex={0} data-id={task.id} style={style} onClick={onOpen} onPointerDown={onPress}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen())}>
      <div className="top">
        <span className="id">{task.id}</span><PullChip pulls={task.prs} />
        {onPlay && !claim && startLane(task) && (
          <button className="play" title={guard || "Start a session"} aria-label={`Start ${task.id}`} disabled={!startable(task)}
            onClick={(e) => { e.stopPropagation(); onPlay(); }} onPointerDown={stop}
            // only the keys that would open the card stop here: the question ▶ asks still answers 1, 2 and Esc while ▶ keeps focus
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && e.stopPropagation()}>▶</button>
        )}
      </div>
      <div className="t">{task.title}</div>
      {claim ? (
        <div className="mach sess">
          <span className="p" /><b>session</b><span className="s">· {claim.phase === "starting" ? "starting" : "waiting for claim"}</span>
          {claim.url && <a className="ago" href={claim.url} target="_blank" rel="noopener" title="Open session" onClick={stop} onPointerDown={stop}>↗</a>}
        </div>
      ) : task.released ? (
        <div className="mach released" title="Left Waiting when its dependencies finished">
          <span className="p" /><b>released</b>
        </div>
      ) : live && (
        <div className={`mach${now - live.at < HOT_S ? " hot" : ""}`}>
          <span className="p" /><b>{live.machine}</b><span className="s">· {live.state.replace(/_/g, " ")}</span><span className="ago">{ago(now - live.at)}</span>
        </div>
      )}
      {!compact && (
        <div className="foot">
          {labels.map((l) => (
            <span key={l} title={l} className={`lab${l === "needs-human" ? " nh" : /^size-/.test(l) ? " sz" : ""}`}>{/^size-/.test(l) ? `${l.slice(5)}pt` : l}</span>
          ))}
          {task.openDeps > 0 && <span className="dep" title="open dependencies">⧗{task.openDeps}</span>}
          {task.assignee ? <span className="who"><i style={{ background: profileColor(task.assignee) }} />{shortProfile(task.assignee)}</span> : <span className="who">unassigned</span>}
        </div>
      )}
      {marks.refusal && <RefusalNote refusal={marks.refusal} names={names} dismiss={dismiss} />}
      {marks.failed && <StartNote id={task.id} failed={marks.failed} names={names} dismiss={dismissStart ?? dismiss} />}
    </div>
  );
}

function Modal({ task, names, marks, now, profiles, milestones, capabilities, close, hide, archive, constellation, move, start, dismiss, dismissStart, saved }: {
  task: KanbanTask; names: Record<string, string>; marks: Marks; now: number; profiles: string[]; milestones: string[];
  capabilities?: { edit: boolean; archive: boolean }; close: () => void; hide: () => void; archive: () => void; constellation: () => void;
  move: (to: string) => void; start: () => void; dismiss: () => void; dismissStart: () => void; saved: (record: TaskRecord) => void;
}) {
  // the snapshot's entry lacks the plan, notes and checks: the full record is read when the task opens, and the entry draws meanwhile
  const [record, setRecord] = useState<TaskRecord | null>(null);
  useEffect(() => {
    let current = true;
    void fetchRecord(task.id).then((r) => current && setRecord(r));
    return () => { current = false; };
  }, [task.id]);
  return (
      <TaskView task={task} record={record} lane={names[task.lane] ?? task.lane} names={names}
        machine={task.live ? `${task.live.machine} · ${task.live.state} · ${ago(now - task.live.at)} ago` : "—"}
        profiles={profiles} milestones={milestones} capabilities={capabilities} saving={!!marks.saving} claiming={!!marks.claim}
        refusal={marks.refusal && <RefusalNote refusal={marks.refusal} names={names} dismiss={dismiss} />}
        startNote={marks.failed && <StartNote id={task.id} failed={marks.failed} names={names} dismiss={dismissStart} />}
        close={close} hide={hide} archive={archive} constellation={constellation} move={move} start={start}
        onSaved={(next) => { setRecord(next); saved(next); }} />
  );
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** One row of the question's choices: a segmented control, each option disabled with its reason when it cannot be picked. */
function Segments({ label, options, value, set }: {
  label: string; options: { value: string; text: string; reason?: string }[]; value: string; set: (v: string) => void;
}) {
  return (
    <div className="row">
      <span className="lb">{label}</span>
      <span className="seg" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button key={o.value} role="radio" aria-checked={o.value === value} className={o.value === value ? "on" : undefined}
            disabled={!!o.reason} title={o.reason} onClick={() => set(o.value)}>{o.text}</button>
        ))}
      </span>
    </div>
  );
}

/** How a move to In progress starts: a session on a picked harness, tier and effort (1), or the task worked by hand (2). */
function StartQuestion({ asking, harnesses, names, canStart, pick, start, manual, cancel }: {
  asking: Asking; harnesses: Harnesses; names: Record<string, string>; canStart: boolean; pick: (change: Partial<Pick>) => void;
  start: () => void; manual: () => void; cancel: () => void;
}) {
  const { task, pick: p } = asking;
  const harness = harnesses.harnesses.find((h) => h.name === p.harness);
  const efforts = harness?.tiers[p.tier]?.efforts ?? [];
  const assignee = profileOf(p);
  return (
    <div id="kbm" onClick={(e) => e.target === e.currentTarget && cancel()}>
      <div className="modal ask" role="dialog" aria-label={`Start ${task.id}`}>
        <div className="k">{task.id} · {names[task.lane] ?? task.lane} → {names.in_progress ?? "In progress"}</div>
        <h2>{task.title}</h2>
        <div className={`opt go${canStart ? "" : " off"}`}>
          {harnesses.harnesses.length > 1 && (
            <Segments label="Harness" value={p.harness} set={(harness) => pick({ harness })}
              options={harnesses.harnesses.map((h) => ({ value: h.name, text: h.label, reason: h.sessions ? undefined : h.reason || "runs no sessions" }))} />
          )}
          {harness && (
            <>
              <Segments label="Tier" value={p.tier} set={(tier) => pick({ tier })}
                options={harnesses.tiers.filter((t) => t in harness.tiers).map((t) => ({ value: t, text: capital(t) }))} />
              <div className="row">
                <span className="lb">Effort</span>
                {efforts.length ? (
                  <span className="seg" role="radiogroup" aria-label="Effort">
                    {efforts.map((e) => (
                      <button key={e} role="radio" aria-checked={e === p.effort} className={e === p.effort ? "on" : undefined} onClick={() => pick({ effort: e })}>{capital(e)}</button>
                    ))}
                  </span>
                ) : <span className="none">none for this tier</span>}
              </div>
              <div className="row"><span className="lb" /><span className="runs">{runsOn(p, harnesses)}</span></div>
              <div className="row">
                <span className="lb">Assignee</span>
                <code>{assignee}</code>
                {assignee !== task.assignee && <span className="was">was {task.assignee || "unassigned"} · saved on start</span>}
              </div>
            </>
          )}
          <button className="startbtn" disabled={!canStart} onClick={start}>▶ Start session <kbd>1</kbd></button>
          <p>{canStart
            ? "Opens a Remote Control session; its agent claims the task, and the card waits in In progress until it does."
            : "No configured harness can open a session here."}</p>
        </div>
        <button className="opt manual" onClick={manual}>
          <span><b>Work it manually</b><br />Moves it to In progress through the board writer. No session starts.</span><kbd>2</kbd>
        </button>
        <div className="afoot"><button className="cancel" onClick={cancel}>Cancel</button><kbd>Esc</kbd></div>
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

export function Kanban({ hud, moves, starts, compact, constellation }: { hud: HudState; moves: MoveStore; starts: StartStore; compact: boolean; constellation: (lane: string) => void }) {
  const [storage] = useState(browserStorage);
  const [prefs, setPrefs] = useState<Prefs>(() => loadPrefs(storage, location.search));
  const [open, setOpen] = useState<string | null>(() => linkedTask(location.search));
  const [menu, setMenu] = useState<MenuName | null>(null);
  const [typing, setTyping] = useState(false);
  const [pick, setPick] = useState(0);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [lift, setLift] = useState<{ id: string; kinds: Record<string, Target>; over: string | null; w: number } | null>(null);
  const [bounced, setBounced] = useState<string | null>(null);
  const [edited, setEdited] = useState<Record<string, { record: TaskRecord; source: KanbanTask[] }>>({});
  // an archived card leaves its column at once; the next snapshot agrees
  const [archiving, setArchiving] = useState<string | null>(null);
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());
  const [toast, setToast] = useState<{ text: string; sub: string } | null>(null);
  const moved = useSyncExternalStore(moves.subscribe, moves.get);
  const started = useSyncExternalStore(starts.subscribe, starts.get);
  // a card dropped on In progress waits where it was dropped until the start question is answered
  const [held, setHeld] = useState<{ id: string; rect: DOMRect; w: number } | null>(null);
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
  /** Answer the start question: a held card flies from its drop point to where the answer puts it, or shakes back on Escape. */
  const answer = useCallback((key: string) => {
    const asked = starts.get().asking;
    if (!starts.key(key)) return false;
    if (held && asked?.task.id === held.id) {
      if (key === "Escape") {
        setBounced(held.id);
        setTimeout(() => setBounced(null), 650);
      } else dropRect.current = { id: held.id, rect: held.rect };
    }
    setHeld(null);
    return true;
  }, [starts, held]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (starts.get().asking) {
        if (!e.metaKey && !e.ctrlKey && !e.altKey && answer(e.key)) e.preventDefault();
        return;
      }
      if (e.key !== "Escape") return;
      setOpen(null);
      setMenu(null);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [starts, answer]);
  // a streamed board ends the moves and refusals it has overtaken, and the claims its agents made or were refused
  useEffect(() => moves.sync(hud.cards), [moves, hud.cards]);
  useEffect(() => starts.sync(hud.cards, hud.claims), [starts, hud.cards, hud.claims]);
  useEffect(() => {
    document.body.classList.toggle("dragging", lift !== null);
    return () => document.body.classList.remove("dragging");
  }, [lift]);
  const cards = useMemo(() => withoutArchived(placeClaims(place(hud.cards, moved), started).map((card) => {
    const saved = edited[card.id];
    return saved?.source === hud.cards ? applyTaskRecord(card, saved.record) : card;
  }), gone), [edited, gone, hud.cards, moved, started]);
  const view = useMemo(() => layout(cards, hud.names, prefs), [cards, hud.names, prefs]);
  const task = open ? cards.find((t) => t.id === open) : undefined;
  const archiveTask = archiving ? cards.find((t) => t.id === archiving) : undefined;
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4200);
    return () => clearTimeout(timer);
  }, [toast]);
  const marksOf = (id: string): Marks => ({ saving: moved.pending[id]?.saving, refusal: moved.refused[id], claim: started.claiming[id], failed: started.failed[id] });
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
  }, [moved.pending, started.claiming]);
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
      if (to && dropAsks(t, to)) {
        if (rect) setHeld({ id: t.id, rect, w: p.w });
        starts.ask(t, "drop");
      } else if (to && (kind === "ok" || kind === "guard")) {
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
  const heldTask = held ? cards.find((t) => t.id === held.id) : undefined;
  const openCard = (id: string) => () => !clickEnds.current && setOpen(id);
  return (
    <main id="kb" className={compact ? "compact" : undefined}>
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
              <h2><span className="g" /><span className="nm" title={col.name}>{col.name}</span><span className="c">{col.count}</span>
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
                      <Card key={t.id} task={t} now={now} names={hud.names} compact={compact} marks={{ ...marksOf(t.id), lifted: lift?.id === t.id || held?.id === t.id }}
                        style={bounced === t.id ? { animation: "kb-shake .65s" } : undefined}
                        onOpen={openCard(t.id)} onPress={canDrag(t.id, started) ? begin(t) : undefined} onPlay={() => starts.ask(t, "play")}
                        dismiss={() => moves.dismiss(t.id)} dismissStart={() => starts.dismiss(t.id)} />
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
          <Card task={lifted} now={now} names={hud.names} compact={compact} marks={{}} onOpen={() => {}} dismiss={() => {}} style={{ width: lift?.w }} />
        </div>
      )}
      {held && heldTask && (
        <div className="lift" style={{ left: held.rect.left, top: held.rect.top }}>
          <Card task={heldTask} now={now} names={hud.names} compact={compact} marks={{}} onOpen={() => {}} dismiss={() => {}} style={{ width: held.w }} />
        </div>
      )}
      {started.asking && (
        <StartQuestion asking={started.asking} harnesses={started.harnesses} names={hud.names} canStart={starts.canStart()} pick={(change) => starts.pick(change)}
          start={() => answer("1")} manual={() => answer("2")} cancel={() => answer("Escape")} />
      )}
      {task && (
        <Modal key={task.id} task={task} names={hud.names} marks={marksOf(task.id)} now={now} capabilities={hud.capabilities}
          profiles={assignees.map((o) => o.value).filter(Boolean)} milestones={milestones.map((o) => o.value).filter(Boolean)} close={() => setOpen(null)}
          hide={() => { setPrefs((p) => hideTask(p, task.id)); setOpen(null); }} archive={() => setArchiving(task.id)} constellation={() => constellation(task.lane)}
          move={(to) => { if (!dropAsks(task, to)) return void moves.drop(task, to); starts.ask(task, "modal"); setOpen(null); }}
          start={() => { starts.ask(task, "modal"); setOpen(null); }}
          dismiss={() => moves.dismiss(task.id)} dismissStart={() => starts.dismiss(task.id)}
          saved={(record) => setEdited((all) => ({ ...all, [task.id]: { record, source: hud.cards } }))} />
      )}
      {archiveTask && (
        <ArchiveDialog key={archiveTask.id} task={archiveTask} lane={hud.names[archiveTask.lane] ?? archiveTask.lane} close={() => setArchiving(null)}
          archived={(reason) => {
            setGone((ids) => new Set(ids).add(archiveTask.id));
            setArchiving(null);
            setOpen(null);
            setToast({ text: `${archiveTask.id} archived`, sub: reason ? "reason saved as a task comment" : "no reason given" });
          }} />
      )}
      {toast && <div id="ef-toast" role="status">{toast.text}<span>  ·  {toast.sub}</span></div>}
    </main>
  );
}
