// The Kanban view: the Board's open tasks as six columns of milestone buckets, with drag and modal moves and sessions started from a card.
// The model is kanban.ts, move.ts and start.ts; this draws them.
import { Fragment, memo, startTransition, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { archiveDialogKey, withoutArchived } from "./archive";
import { ChoiceMenu } from "../../shared/ChoiceMenu";
import { ArchiveDialog } from "./ArchiveConfirm";
import { useViewActive } from "../../shared/Kept";
import { Viewport, ViewportRow } from "../../shared/ViewportRows";
import { ago } from "../../shared/clock";
import type { HudState } from "../../render/hud";
import {
  CLOSED, applySuggestion, applyTaskRecord, assigneeOptions, chainOf, claimChip, clearFilters, columnsOf, filtersActive, hideMilestone, hideTask, holdCounts, holders, labelSuggestions, layout, milestoneOptions, milestoneOutline, recent, show, showAll,
  stacked as stacksState, stackOf, stackStep, toggleFold, unheld, unheldShown, unstacked, whyHidden,
  type ClaimChip, type KanbanTask, type Prefs, type Stack, type StackEvent, type StackOpen,
} from "./kanbanModel";
import { sessionNickname } from "./nickname";
import { linkedTask, loadPrefs, savePrefs, withoutFilters } from "./kanbanPrefs";
import { codeParts, place, targets, type MoveStore, type Refusal, type Target } from "./move";
import { browserStorage, PHONE } from "../../shared/nav";
import {
  canDrag, dropAsks, placeClaims, profileOf, profilesOf, runsOn, startLane, startable,
  type Asking, type Claiming, type Failed, type Harnesses, type Pick, type StartStore,
} from "./start";
import { MilestoneOutline } from "./MilestoneOutline";
import { NewTaskAction } from "./NewTask";
import { SearchClear } from "../../shared/SearchClear";
import { useScrollRest } from "../../shared/scrollRest";
import { TaskView } from "./TaskView";
import { PRE_DRAW_REST_MS, READ_AHEAD_MS, RecordCache, fetchRecord, type TaskRecord } from "./taskViewModel";
import type { Capabilities, Pull, Roles } from "../../api";

/** A milestone's header: the key the snapshot carries, or the bucket for tasks with none. */
const milestoneName = (milestone: string) => milestone || "No milestone";
/** A machine event this recent still pulses on its card, in seconds. */
const HOT_S = 120;

const profileColor = (a: string) => (/deep/.test(a) ? "var(--agent)" : /standard/.test(a) ? "var(--waits)" : /fast/.test(a) ? "var(--run)" : "var(--slate)");
/** An assignee as a card draws it: a session URL is its nickname, a profile name loses its `@agent-` prefix. */
const shortProfile = (a: string) => sessionNickname(a) ?? a.replace(/^@agent-/, "").replace(/^@/, "");
/** A card draws this many PR chips; the rest fold into one `+N` chip whose hover lists them. */
const SHOWN_PRS = 3;
const checksClass = (p: Pull) => (p.merged ? "merged" : p.closed ? "closed" : p.checks === "failing" ? "fail" : p.checks);
const pullClass = (p: Pull) => `${checksClass(p)}${p.conflicting && !p.merged && !p.closed ? " conflict" : ""}`;
const pullState = (p: Pull) =>
  [p.merged ? "merged" : p.closed ? "closed" : `checks ${p.checks}`, p.conflicting && !p.merged && !p.closed && "merge conflict", p.threads && `${p.threads} open review threads`]
    .filter(Boolean).join(", ") + (p.stale ? " (not read yet)" : "");
/** The `+N` chip's state: the worst among the PRs it hides, so a failure or conflict past the third still shows. */
const RANK = ["fail", "pending", "pass", "none", "merged", "closed"];
const worstClass = (pulls: Pull[]) => {
  const worst = pulls.map(checksClass).sort((a, b) => RANK.indexOf(a) - RANK.indexOf(b))[0];
  return `${worst}${pulls.some((p) => p.conflicting && !p.merged && !p.closed) ? " conflict" : ""}`;
};

/** Each pull request's chip; its checks dot only when the card's machine line is not CI, since a CI line carries the state. */
function PullChips({ pulls, ci }: { pulls: Pull[]; ci: boolean }) {
  if (!pulls.length) return null;
  const rest = pulls.slice(SHOWN_PRS);
  return (
    <span className="prs">
      {pulls.slice(0, SHOWN_PRS).map((p) => (
        <span key={p.url} className={`pr ${pullClass(p)}`} title={`#${p.number} ${pullState(p)}`}>
          {!ci && <i />}#{p.number}
          {p.threads > 0 && <span className="th"> ⌁{p.threads}</span>}
        </span>
      ))}
      {rest.length > 0 && (
        <span className={`pr more ${worstClass(rest)}`} title={rest.map((p) => `#${p.number} ${pullState(p)}`).join("\n")}>
          +{rest.length}
        </span>
      )}
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

/** Where a card sits in the hovered card's chain: the hovered card, a Waiting task it holds or an open task it waits on. */
export type Chain = "self" | "holds" | "waits";

/** A task card; compact keeps the id, pull request, title and machine line and drops the footer of labels, dependencies and profile. */
export function Card({ task, holds = 0, chain, stacked = 0, under = false, links, cross, onCross, now, marks, names, roles, compact = false, onOpen, onPress, onPlay, onHover, onAhead, dismiss, dismissStart, style }: {
  task: KanbanTask; holds?: number; chain?: Chain;
  /** The tasks stacked under this one, on a stack's top card; whether this card sits under one, and while that stack is unstacked the open tasks it waits on, or the Done tasks it unblocked. */
  stacked?: number; under?: boolean; links?: string[];
  /** The Waiting blockers in other milestones, each drawn as a link badge in the footer that opens that task through `onCross`. */
  cross?: KanbanTask[]; onCross?: (id: string) => void; now: number; marks: Marks; names: Record<string, string>; roles: Roles; compact?: boolean; onOpen: () => void; onPress?: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPlay?: () => void; onHover?: (on: boolean) => void; onAhead?: () => void; dismiss: () => void; dismissStart?: () => void; style?: CSSProperties;
}) {
  const live = task.live, claim = marks.claim;
  const playing = onPlay && !claim && startLane(task, roles);
  const cls = ["card", chain && `chain-${chain}`, under && "under", compact && "compact", playing && "startable", marks.saving && "saving", (marks.refusal || marks.failed) && "bad", marks.lifted && "ghost", claim && "claiming"].filter(Boolean).join(" ");
  const finished = task.lane === roles.done;
  const chip = claimChip(task, roles, now);
  // a Waiting stack's ⛓ already counts what it holds; only a Done chain adds the green count
  const badge = stacked > 0 && finished && <StackBadge count={stacked} />;
  const working = roles.working ? task.moves[roles.working] : undefined;
  const guard = working?.allowed === false ? working.reason : "";
  return (
    <div className={cls} role="button" tabIndex={0} data-id={task.id} style={style} onClick={onOpen} onPointerDown={(e) => { onAhead?.(); onPress?.(e); }} onFocus={onAhead}
      onPointerEnter={onHover && (() => onHover(true))} onPointerLeave={onHover && (() => onHover(false))}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen())}>
      <div className="top">
        <span className="id">{task.id}</span><PullChips pulls={task.prs} ci={task.live?.machine === "ci"} />{compact && badge}
      </div>
      {links && links.length > 0 && <div className={`uw${finished ? " dn" : ""}`}><span className="nw">{finished ? "✓ unblocked" : "⧗ waits on"}</span>{" "}{links.map((id, i) => <Fragment key={id}>{i > 0 && ", "}<span className="nw">{id}</span></Fragment>)}</div>}
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
          <span className={live.source ? "p mapped" : "p"} title={live.source ? `mapped from ${live.source}` : undefined} /><b>{live.machine}</b><span className="s">· {live.state.replace(/_/g, " ")}</span><span className="ago">{ago(now - live.at)}</span>
        </div>
      )}
      {!compact && (
        <div className="foot">
          {badge}
          {holds > 0 && <span className="holds" title={`holds ${holds} Waiting task${holds === 1 ? "" : "s"}`}>⛓{holds}</span>}
          {task.openDeps > 0 && <span className="dep" title="open dependencies">⧗{task.openDeps}</span>}
          {cross?.map((d) => (
            // a button of its own on the card: it opens the blocker, so the click, press and keys that would open or lift the card stop here
            <button key={d.id} className="xm" title={`Waits on ${d.id} in ${d.milestone || "No milestone"} (Waiting): open it`}
              onClick={(e) => { e.stopPropagation(); onCross?.(d.id); }} onPointerDown={stop}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && e.stopPropagation()}>
              ↗ <span className="nw">{d.milestone || "no milestone"}</span> · <span className="nw">{d.id}</span>
            </button>
          ))}
          {chip ? <ClaimWho chip={chip} /> : task.assignee ? <span className="who"><i style={{ background: profileColor(task.assignee) }} />{shortProfile(task.assignee)}</span> : <span className="who">unassigned</span>}
        </div>
      )}
      {playing && (
        // a full-height strip on the card's right edge, so a near miss lands on the card and opens the task
        <button className="play edge" title={guard || "Start a session"} aria-label={`Start ${task.id}`} disabled={!startable(task, roles)}
          onClick={(e) => { e.stopPropagation(); onPlay(); }} onPointerDown={stop}
          // only the keys that would open the card stop here: the question ▶ asks still answers 1, 2 and Esc while ▶ keeps focus
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && e.stopPropagation()}>▶</button>
      )}
      {marks.refusal && <RefusalNote refusal={marks.refusal} names={names} dismiss={dismiss} />}
      {marks.failed && <StartNote id={task.id} failed={marks.failed} names={names} dismiss={dismissStart ?? dismiss} />}
    </div>
  );
}

/** The footer chip of a working card whose claim lapsed or is about to: the expired session struck through, or the held one's minutes left. */
function ClaimWho({ chip }: { chip: ClaimChip }) {
  const session = shortProfile(chip.session);
  if (chip.kind === "near")
    return (
      <span className="who near" title={`Held by ${session}: the claim expires in ${chip.minutes}m unless the session acts.`}>
        <i style={{ background: profileColor(chip.session) }} />{session}<span className="tl">· {chip.minutes}m left</span>
      </span>
    );
  return (
    <span className="who unheld" title={`Unheld: ${session}'s claim expired ${chip.age} ago. Any session may claim it.`}>
      <i className="o" style={{ borderColor: profileColor(chip.session) }} /><s>{session}</s><span className="tl">· expired {chip.age}</span>
    </span>
  );
}

/** The green count on a Done chain's top card: the Done tasks its chain finished first. */
function StackBadge({ count }: { count: number }) {
  return (
    <span className="sk dn" title={`${count} Done task${count === 1 ? "" : "s"} this one's chain finished first; hover to unstack`}>
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="2.5" y="2" width="11" height="7" rx="1.5" /><path d="M3.5 11.5h9M5 14h6" /></svg>{count}
    </span>
  );
}

/** How a stack's cards are drawn: the card for a task, with what the stack adds to it. */
const HANDLERS = new Set(["onCross", "onOpen", "onPress", "onPlay", "onHover", "onAhead", "dismiss", "dismissStart"]);
const same = (a: unknown, b: unknown) => {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => x === b[i]);
  if (a && b && typeof a === "object" && typeof b === "object") {
    const x = a as Record<string, unknown>, y = b as Record<string, unknown>;
    return Object.keys({ ...x, ...y }).every((k) => x[k] === y[k]);
  }
  return false;
};
/** The clock only reaches a card through its machine line and its claim chip: whether the line is hot, its age text and the chip's. */
const stamp = (t: KanbanTask, roles: Roles, now: number) =>
  `${t.live ? `${now - t.live.at < HOT_S} ${ago(now - t.live.at)}` : ""} ${JSON.stringify(claimChip(t, roles, now))}`;
/**
 * A card redraws when something it shows changes. Its handlers are rebuilt on every board render yet act on the same task through stable stores,
 * so only whether one is set counts, and a tick of the clock redraws only the cards whose stamp text moved.
 */
const BoardCard = memo(Card, (before, after) =>
  stamp(before.task, before.roles, before.now) === stamp(after.task, after.roles, after.now) &&
  Object.keys({ ...before, ...after }).every((k) => {
    const key = k as keyof typeof before;
    if (key === "now") return true;
    return HANDLERS.has(k) ? !before[key] === !after[key] : same(before[key], after[key]);
  }));

type DrawCard = (task: KanbanTask, extra?: { stacked?: number; under?: boolean; links?: string[] }) => ReactNode;

/**
 * One Waiting stack or Done chain. Folded, the top card is whole and one or two card edges peek below it; unstacked, the cards under it open downward,
 * pushing what is below, each saying what it waits on, or in a Done chain which task it unblocked. The rest are always drawn so the unfold can animate; the style hides them folded.
 */
export function StackView({ stack, state, onEvent, card }: { stack: Stack; state: StackOpen; onEvent: (e: StackEvent) => void; card: DrawCard }) {
  const open = unstacked(state), under = stack.members.slice(1);
  return (
    <div className={`stack${open ? " open" : ""}`} style={{ "--peek": `${Math.min(2, under.length) * 5}px` } as CSSProperties}
      onPointerEnter={() => onEvent("enter")} onPointerLeave={() => onEvent("leave")} onFocus={() => onEvent("focus")}
      onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node | null) && onEvent("blur")}
      onKeyDown={(e) => e.key === "Escape" && onEvent("escape")}>
      {under.slice(0, 2).map((t, i) => <div key={t.id} className="edge" style={{ "--i": i } as CSSProperties} />)}
      <div className="spine" />
      {card(stack.top, { stacked: under.length })}
      <div className="rest"><div className="restin">
        {under.map((t) => card(t, { under: true, links: open ? stack.links.get(t.id) : undefined }))}
      </div></div>
    </div>
  );
}

/** Milliseconds the pointer rests on a stack before it unstacks, so sweeping across a column does not open every stack it crosses. */
const INTENT_MS = 1000;

function OpenStack({ stack, card, enabled }: { stack: Stack; card: DrawCard; enabled: boolean }) {
  const [state, setState] = useState(CLOSED);
  const intent = useRef<number>(undefined);
  useEffect(() => () => clearTimeout(intent.current), []);
  const onEvent = (e: StackEvent) => {
    if (e === "enter") {
      if (enabled) intent.current = window.setTimeout(() => setState((s) => stackStep(s, "enter")), INTENT_MS);
      return;
    }
    if (e === "leave") clearTimeout(intent.current);
    setState((s) => stackStep(s, e));
  };
  return <StackView stack={stack} state={state} onEvent={onEvent} card={card} />;
}

/** A bucket's Waiting stacks or Done chains: a task with nothing stacked under it is a plain card. */
export function Stacks({ stacks, card, enabled }: { stacks: Stack[]; card: DrawCard; enabled: boolean }) {
  return <>{stacks.map((s) => (s.members.length > 1 ? <OpenStack key={s.top.id} stack={s} card={card} enabled={enabled} /> : card(s.top)))}</>;
}

/** The Waiting stack or Done chain in the task modal: its members top first, each opening its own task. */
export function StackList({ stack, id, open }: { stack: Stack; id: string; open: (id: string) => void }) {
  return (
    <>
      {stack.members.map((t, i) => (
        <div key={t.id}>{i ? "↳ " : "▣ "}{t.id === id ? <b>{t.id}</b> : <button onClick={() => open(t.id)} title={t.title}>{t.id}</button>}</div>
      ))}
    </>
  );
}

/** The Waiting column's strip: the tasks at the bottom of its chains, most held first, each opening its card. */
export function HeldBy({ holders: held, roles, open, hover }: {
  holders: { task: KanbanTask; holds: number }[]; roles: Roles; open: (id: string) => void; hover?: (id: string | null) => void;
}) {
  if (!held.length) return null;
  return (
    <div className="heldby">
      <span className="k" title="The tasks every Waiting chain ends at; finishing one releases the Waiting tasks it holds">Held by</span>
      {held.slice(0, 3).map(({ task, holds }) => (
        <button key={task.id} className={`hb${task.lane === roles.attention ? " nh" : ""}`} onClick={() => open(task.id)}
          onPointerEnter={hover && (() => hover(task.id))} onPointerLeave={hover && (() => hover(null))}
          title={`${task.title} · ${task.lane.replace(/_/g, " ")} · holds ${holds} Waiting task${holds === 1 ? "" : "s"}`}>
          {task.id}<b>⛓{holds}</b>
        </button>
      ))}
      {held.length > 3 && <span className="more">+{held.length - 3} more</span>}
    </div>
  );
}

function Modal({ task, tasks, records, stack, names, roles, marks, now, profiles, milestones, capabilities, close, open, hide, archive, constellation, move, start, dismiss, dismissStart, saved }: {
  task: KanbanTask; tasks: KanbanTask[]; records: RecordCache; stack?: ReactNode; names: Record<string, string>; roles: Roles; marks: Marks; now: number; profiles: string[]; milestones: string[];
  capabilities?: Capabilities; close: () => void; open: (id: string) => void; hide: () => void; archive: () => void; constellation: () => void;
  move: (to: string) => void; start: () => void; dismiss: () => void; dismissStart: () => void; saved: (record: TaskRecord) => void;
}) {
  // the snapshot's entry lacks the plan, notes and checks: a record read while the pointer rested on the card draws at once;
  // otherwise it is read when the task opens, and the entry draws meanwhile
  const [held] = useState(() => records.fresh(task.id));
  const [record, setRecord] = useState<TaskRecord | null>(() => (held ?? records.last(task.id))?.got ?? null);
  // a read that fails is shown, with a retry, rather than leaving the modal busy for good
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    // the read ahead is awaited even once it has landed, since it may have landed after this render initialized `record`;
    // one that failed is read once more rather than shown
    void (!attempt && held ? held.read.then((r) => r ?? fetchRecord(task.id)) : fetchRecord(task.id)).then((r) => {
      if (!current) return;
      setRecord(r);
      setFailed(!r);
    });
    return () => { current = false; };
  }, [held, task.id, attempt]);
  return (
      <TaskView task={task} tasks={tasks} record={record} stack={stack} lane={names[task.lane] ?? task.lane} names={names} roles={roles} now={now} open={open}
        profiles={profiles} milestones={milestones} capabilities={capabilities} saving={!!marks.saving} claiming={!!marks.claim}
        refusal={marks.refusal && <RefusalNote refusal={marks.refusal} names={names} dismiss={dismiss} />}
        startNote={marks.failed && <StartNote id={task.id} failed={marks.failed} names={names} dismiss={dismissStart} />}
        readNote={failed && <div className="editrefusal" role="alert"><b>The full record could not be read.</b> <button className="hidebtn" onClick={() => { setFailed(false); setAttempt((n) => n + 1); }}>Retry</button></div>}
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

/** How a move to In progress starts: a session on a picked harness, tier and effort (1), or the task worked by hand (2). The picks sit on one label/value grid and the answers on one footer
 *  row, as the confirmation box lays its own out. */
export function StartQuestion({ asking, harnesses, names, canStart, pick, start, manual, cancel }: {
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
        <div className="k">{task.id} · {names[task.lane] ?? task.lane} → {names[asking.working] ?? asking.working}</div>
        <h2>{task.title}</h2>
        <div className="sh">Session</div>
        <div className={`opt${canStart ? "" : " off"}`}>
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
              <div className="row"><span className="lb">Runs</span><span className="runs">{runsOn(p, harnesses).replace(/^runs /, "")}</span></div>
              <div className="row">
                <span className="lb">Assignee</span>
                <span><code>{assignee}</code>{assignee !== (task.profile ?? task.assignee) && <span className="was">was {(task.profile ?? task.assignee) || "unassigned"} · saved on start</span>}</span>
              </div>
            </>
          )}
          {!harness && <span className="none wide">No configured harness can open a session here.</span>}
        </div>
        <p className="note">
          <b>Start session</b> opens a Remote Control session; its agent claims the task, and the card waits in In progress until it does.
          {" "}<b>Work it manually</b> moves it through the board writer; no session starts.
        </p>
        <div className="afoot">
          <button className="cancel" onClick={cancel}>Cancel <kbd>Esc</kbd></button>
          <span className="sp" />
          <button className="manual" onClick={manual}>Work it manually <kbd>2</kbd></button>
          <button className="startbtn" disabled={!canStart} onClick={start}>▶ Start session <kbd>1</kbd></button>
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

/** Each declared state type's mark: a column header says what kind of state the machine declares it, whatever the state is called. */
const TYPE_MARKS: Record<string, ReactNode> = {
  initial: <path className="f" d="M3.3 2.2v5.6L8 5z" />,
  resting: <circle className="f" cx="5" cy="5" r="3" />,
  waiting_on_fact: <><circle cx="5" cy="5" r="3.8" /><path d="M5 2.9v2.3l1.5 1" /></>,
  waiting_on_person: <><circle className="f" cx="5" cy="3.2" r="1.7" /><path className="f" d="M1.8 9.2c.3-2.1 1.6-3.3 3.2-3.3s2.9 1.2 3.2 3.3z" /></>,
  final: <><circle cx="5" cy="5" r="3.8" /><path d="M3.2 5.1l1.3 1.3 2.4-2.6" /></>,
};
const TYPE_NAMES: Record<string, string> = { waiting_on_fact: "waiting on a fact", waiting_on_person: "waiting on a person" };

function TypeGlyph({ type }: { type?: string | null }) {
  const known = type && type in TYPE_MARKS ? type : null, name = known ? `Type: ${TYPE_NAMES[known] ?? known}` : "No declared type";
  return (
    <svg className="rg" data-type={known ?? "none"} viewBox="0 0 10 10" role="img" aria-label={name}>
      <title>{name}</title>{known ? TYPE_MARKS[known] : <circle className="f" cx="5" cy="5" r="1.4" />}
    </svg>
  );
}

type MenuName = "assignee" | "milestone" | "hidden";

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
/** The task whose modal is open. The Kanban only writes it and the modal host alone reads it, so opening or closing a task leaves the board undrawn. */
class OpenTask {
  private fns = new Set<() => void>();
  private pre: string | null = null;
  constructor(private id: string | null) {}
  get = () => this.id;
  /** The task whose modal is drawn hidden ahead of its click, while no modal is open. */
  ahead = () => this.pre;
  set = (id: string | null) => {
    if (id === this.id) return;
    this.id = id;
    this.pre = null;
    this.fns.forEach((fn) => fn());
  };
  ready = (id: string | null) => {
    if (this.id !== null || id === this.pre) return;
    this.pre = id;
    this.fns.forEach((fn) => fn());
  };
  subscribe = (fn: () => void) => {
    this.fns.add(fn);
    return () => void this.fns.delete(fn);
  };
}

/**
 * The open task's modal, drawn by `draw`; a task with no card opens no modal. While none is open, the modal of the card the
 * pointer rests on is drawn hidden and inert, so its click only shows it. That draw is a transition: a click landing first
 * draws the modal itself, as it would with nothing ahead.
 */
function ModalHost({ store, cards, draw }: { store: OpenTask; cards: KanbanTask[]; draw: (task: KanbanTask) => ReactNode }) {
  const id = useSyncExternalStore(store.subscribe, store.get);
  const [ahead, setAhead] = useState(store.ahead);
  useEffect(() => store.subscribe(() => startTransition(() => setAhead(store.ahead()))), [store]);
  const task = cards.find((t) => t.id === (id ?? ahead));
  // the same element while the task and `draw` hold, so the click that shows the modal drawn ahead changes `inert` and leaves its tree undrawn
  const modal = useMemo(() => task && draw(task), [task, draw]);
  return task ? <div className="mh" inert={id === null}>{modal}</div> : null;
}

/** Pixels a press travels before it lifts the card instead of opening it. */
const LIFT_PX = 5;

/**
 * The Kanban view. `spot` is the task a Recent line is hovered for: its card lights as a hovered card does and its column scrolls to it,
 * and `note` hears why it has no card in view. A new `opening` opens that task's modal.
 * `searchSlot` is the navigator's search slot, where the text search draws; `onQuery` hears what it holds.
 * `outlineSlot` is the navigator's outline slot, where the milestone outline draws and sets the Milestone filter.
 */
function KanbanView({ hud, moves, starts, compact, constellation, searchSlot, outlineSlot, onQuery, spot = null, note, opening = null, records: adopted }: {
  hud: HudState; moves: MoveStore; starts: StartStore; compact: boolean; constellation: (lane: string) => void; searchSlot: HTMLElement | null; outlineSlot: HTMLElement | null; onQuery?: (query: string) => void;
  spot?: string | null; note?: (why: string | null) => void; opening?: { id: string } | null;
  /** The records the boot read ahead, which this keeps rather than starting its own. */
  records?: RecordCache;
}) {
  // the view stays mounted behind the one showing: its navigator slots, dialogs, keys and clock rest until it shows again
  const active = useViewActive();
  const [storage] = useState(browserStorage);
  const [prefs, setPrefs] = useState<Prefs>(() => loadPrefs(storage, location.search));
  const [openTask] = useState(() => new OpenTask(linkedTask(location.search)));
  const setOpen = openTask.set;
  const [records] = useState(() => adopted ?? new RecordCache());
  // the card the pointer rests on, and the timer that draws its modal hidden once it has rested; the record read on hover
  // fills that modal when it lands, so a slow server delays the record, never the drawing
  const resting = useRef<{ id: string | null; timer?: ReturnType<typeof setTimeout> }>({ id: null });
  const rest = (id: string, on: boolean) => {
    clearTimeout(resting.current.timer);
    if (!on) {
      if (resting.current.id === id) resting.current = { id: null };
      if (openTask.ahead() === id) openTask.ready(null);
      return;
    }
    records.readAhead(id);
    resting.current = { id, timer: setTimeout(() => {
      openTask.ready(id);
      // a modal drawn ahead keeps the record it was drawn with: past the read-ahead window, the click reads it again
      resting.current.timer = setTimeout(() => openTask.ahead() === id && openTask.ready(null), READ_AHEAD_MS);
    }, PRE_DRAW_REST_MS) };
  };
  useEffect(() => () => clearTimeout(resting.current.timer), []);
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
  const searchBox = useRef<HTMLInputElement>(null);
  const columns = useRef<HTMLDivElement>(null);
  const ghost = useRef<HTMLDivElement>(null);
  const press = useRef<Press | null>(null);
  const dropRect = useRef<{ id: string; rect: DOMRect } | null>(null);
  const clickEnds = useRef(false);
  // the "ago" stamps keep counting between snapshots
  useEffect(() => {
    if (!active) return;
    const tick = () => setNow(Date.now() / 1000);
    const catchUp = setTimeout(tick, 0); // the stamps stood still while the view was away
    const timer = setInterval(tick, 30_000);
    return () => { clearTimeout(catchUp); clearInterval(timer); };
  }, [active]);
  // a scrolling column stands its cards aside, so those passing under a still pointer neither light, read nor draw ahead
  useScrollRest(columns, ".body");
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
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (starts.get().asking) {
        if (!e.metaKey && !e.ctrlKey && !e.altKey && answer(e.key)) e.preventDefault();
        return;
      }
      if (e.key !== "Escape") return;
      setMenu(null);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [starts, answer, active]);
  // a streamed board ends the moves and refusals it has overtaken, and the claims its agents made or were refused
  useEffect(() => moves.sync(hud.cards), [moves, hud.cards]);
  useEffect(() => starts.sync(hud.cards, hud.claims), [starts, hud.cards, hud.claims]);
  useEffect(() => {
    document.body.classList.toggle("dragging", lift !== null);
    return () => document.body.classList.remove("dragging");
  }, [lift]);
  const { roles } = hud;
  const cards = useMemo(() => withoutArchived(placeClaims(place(hud.cards, moved), started, roles).map((card) => {
    const saved = edited[card.id];
    return saved?.source === hud.cards ? applyTaskRecord(card, saved.record) : card;
  }), gone), [edited, gone, hud.cards, moved, started, roles]);
  const unheldCount = unheldShown(cards, roles, prefs).length;
  const [unheldOnly, setUnheldOnly] = useState(false);
  // the filter ends with the last unheld task, so the next one to lapse does not arrive on a board already filtered
  if (unheldOnly && unheldCount === 0) setUnheldOnly(false);
  const lane = useMemo(() => (unheldOnly ? cards.filter((t) => t.lane !== roles.working || unheld(t, roles)) : cards), [cards, roles, unheldOnly]);
  const view = useMemo(() => layout(lane, hud.names, roles, prefs, now), [lane, hud.names, roles, prefs, now]);
  const holds = useMemo(() => holdCounts(cards, roles), [cards, roles]);
  const blockers = useMemo(() => holders(cards, roles, holds), [cards, roles, holds]);
  const [pointed, setHovered] = useState<string | null>(null);
  // a card the Recent rail points at draws as the hovered one, ringed even when it holds and waits on nothing, since no pointer is on it
  const hovered = pointed ?? spot;
  const chain = useMemo(() => {
    const c = hovered && !lift ? chainOf(cards, hovered, roles) : null;
    if (!c || (!c.holds.size && !c.waitsOn.size && hovered !== spot)) return null;
    return (id: string): Chain | undefined => (id === hovered ? "self" : c.holds.has(id) ? "holds" : c.waitsOn.has(id) ? "waits" : undefined);
  }, [cards, hovered, lift, roles, spot]);
  useEffect(() => {
    if (!spot) return void note?.(null);
    note?.(whyHidden(cards, hud.names, roles, prefs, spot, now));
    document.querySelector<HTMLElement>(`#cols .card[data-id="${spot}"]`)?.scrollIntoView({ block: "nearest" });
  }, [spot, cards, hud.names, roles, prefs, note, now]);
  // each click is a new object, so the same line clicked twice opens it twice; a task with no card opens no modal
  const opened = useRef(opening);
  useLayoutEffect(() => {
    if (opening === opened.current) return;
    opened.current = opening;
    if (opening) openTask.set(opening.id);
  }, [opening, openTask]);
  const archiveTask = archiving ? cards.find((t) => t.id === archiving) : undefined;
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4200);
    return () => clearTimeout(timer);
  }, [toast]);
  const marksOf = (id: string): Marks => ({ saving: moved.pending[id]?.saving, refusal: moved.refused[id], claim: started.claiming[id], failed: started.failed[id] });
  const lanes = useMemo(() => columnsOf(hud.names, roles), [hud.names, roles]);
  const drawn = useMemo(() => recent(cards, now, roles), [cards, now, roles]);
  const suggestions = useMemo(() => labelSuggestions(drawn, prefs.query, lanes), [drawn, prefs.query, lanes]);
  const at = Math.min(pick, suggestions.length - 1);
  const assignees = useMemo(() => assigneeOptions(drawn, lanes), [drawn, lanes]);
  const milestones = useMemo(() => milestoneOptions(drawn, lanes), [drawn, lanes]);
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
    if (e.button !== 0 || (e.target as HTMLElement).closest(".refusal") || window.matchMedia?.(PHONE).matches) return;
    const box = e.currentTarget.getBoundingClientRect();
    const p: Press = { task: t, kinds: targets(t, lanes), x: e.clientX, y: e.clientY, dx: e.clientX - box.left, dy: e.clientY - box.top, w: box.width, lifted: false };
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
      if (to && dropAsks(t, to, roles)) {
        if (rect) setHeld({ id: t.id, rect, w: p.w });
        starts.ask(t, "drop", roles);
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
  useEffect(() => { onQuery?.(prefs.query); }, [onQuery, prefs.query]);
  const lifted = lift ? cards.find((t) => t.id === lift.id) : undefined;
  const heldTask = held ? cards.find((t) => t.id === held.id) : undefined;
  const openCard = (id: string) => () => !clickEnds.current && setOpen(id);
  const drawCard: DrawCard = (t, extra) => (
    <BoardCard key={t.id} task={t} holds={holds.get(t.id)} chain={chain?.(t.id)} cross={view.cross.get(t.id)} onCross={setOpen} {...extra} now={now} names={hud.names} roles={roles} compact={compact} marks={{ ...marksOf(t.id), lifted: lift?.id === t.id || held?.id === t.id }}
      style={bounced === t.id ? { animation: "kb-shake .65s" } : undefined}
      onOpen={openCard(t.id)} onPress={canDrag(t.id, started) ? begin(t) : undefined} onPlay={() => starts.ask(t, "play", roles)} onAhead={() => records.readAhead(t.id)}
      onHover={(on) => { rest(t.id, on); setHovered((h) => (on ? t.id : h === t.id ? null : h)); }}
      dismiss={() => moves.dismiss(t.id)} dismissStart={() => starts.dismiss(t.id)} />
  );
  const outline = useMemo(() => milestoneOutline(cards, roles, hud.milestoneDone), [cards, roles, hud.milestoneDone]);
  // phone width: the lane showing, the working lane first as the lane a phone is most often opened to check, else the board's first
  const [phoneLane, setPhoneLane] = useState<string | null>(null);
  const wanted = phoneLane ?? roles.working;
  const shownLane = view.columns.some((c) => c.id === wanted) ? wanted : view.columns[0]?.id;
  return (
    <main id="kb" className={compact ? "compact" : undefined}>
      <header><span className="title">Kanban</span><span className="count">{view.open} open · {view.done} done</span></header>
      {active && searchSlot && createPortal(
        <div className="fw">
          <input id="kbq" ref={searchBox} type="text" value={prefs.query} placeholder="filter by id, title or label…" aria-label="Filter tasks by id, title or label" autoComplete="off" spellCheck={false}
            onChange={(e) => { setPrefs((p) => ({ ...p, query: e.target.value })); setPick(0); }}
            onFocus={() => setTyping(true)} onBlur={() => setTyping(false)} onKeyDown={onSearchKey} />
          <SearchClear input={searchBox} value={prefs.query} clear={() => { setPrefs((p) => ({ ...p, query: "" })); setPick(0); }} />
          {typing && suggestions.length > 0 && (
            <div className="menu sug" role="listbox" aria-label="Labels">
              <div className="hd">Filter by label</div>
              {suggestions.map((s, i) => (
                <button key={s.label} role="option" aria-selected={i === at} className={i === at ? "on" : undefined}
                  onMouseDown={(e) => e.preventDefault()} onClick={() => choose(s.label)}>{s.label}<span>{s.count}</span></button>
              ))}
            </div>
          )}
        </div>,
        searchSlot,
      )}
      {active && outlineSlot && createPortal(<MilestoneOutline rows={outline} chosen={prefs.milestone} choose={(milestone) => setPrefs((p) => ({ ...p, milestone }))} />, outlineSlot)}
      <div className="filters">
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
        <div className="rt">
          <span className="shown">{view.shown} of {view.total} tasks</span>
          <span className="nt">
            <NewTaskAction capabilities={hud.capabilities} lane={hud.names[lanes[0]] ?? lanes[0]}
              assignees={assignees.map((o) => o.value).filter(Boolean)} milestones={milestones.map((o) => o.value).filter(Boolean)}
              created={(id) => setToast({ text: `${id} created`, sub: `in ${hud.names[lanes[0]] ?? lanes[0]}` })} />
          </span>
        </div>
      </div>
      <div className="lanes" role="tablist" aria-label="Lanes">
        {view.columns.map((col) => (
          <button key={col.id} role="tab" data-lane={col.id} data-role={col.role} aria-selected={col.id === shownLane} title={col.name} onClick={() => setPhoneLane(col.id)}>
            <TypeGlyph type={hud.types?.[col.id]} /><span className="c">{col.count}</span><span className="nm">{col.name}</span>
          </button>
        ))}
      </div>
      <div id="cols" ref={columns} data-warm-parts="" style={{ "--cols": view.columns.length } as CSSProperties}>
        {view.columns.map((col) => {
          let row = 0;
          const target = lift?.kinds[col.id];
          const inChain = chain ? col.buckets.flatMap((b) => b.tasks).filter((t) => chain(t.id) === "holds" || chain(t.id) === "waits").length : 0;
          const colCls = ["col", col.id === shownLane && "on", target && target.kind !== "here" && target.kind, lift?.over === col.id && target?.kind !== "here" && "over"].filter(Boolean).join(" ");
          return (
            <section key={col.id} className={colCls} data-lane={col.id} data-role={col.role}>
              <h2><TypeGlyph type={hud.types?.[col.id]} /><span className="nm" title={col.name}>{col.name}</span><span className="c">{col.count}</span>
                {col.id === roles.working && unheldCount > 0 && (
                  <button className={`uh${unheldOnly ? " on" : ""}`} aria-pressed={unheldOnly} title={unheldOnly ? "Show every In Progress task" : "Show only the In Progress tasks no session holds"}
                    onClick={() => setUnheldOnly((v) => !v)}>{unheldCount} unheld</button>
                )}
                {inChain > 0 && <span className="cc" title={`${inChain} of this column's tasks are in the hovered task's chain`}>⛓{inChain}</span>}
                {target && target.kind !== "here" && (
                  <span className="hint">{target.kind === "ok" ? "drop" : target.kind === "guard" ? `guarded · ${target.skill || "refused"}` : "no transition"}</span>
                )}
              </h2>
              {target?.kind === "guard" && <div className="why"><Reason text={target.reason} /></div>}
              {col.id === roles.waiting && !lift && <HeldBy holders={blockers} roles={roles} open={(id) => setOpen(id)} hover={setHovered} />}
              <Viewport className="body">
                {col.buckets.length === 0 && <div className="empty">no tasks</div>}
                {col.buckets.map((b) => (
                  <div key={b.milestone} className={`bucket${b.folded ? " folded" : ""}`}>
                    <div className="bh" role="button" tabIndex={0} title={milestoneName(b.milestone)} aria-expanded={!b.folded}
                      onClick={() => setPrefs((p) => toggleFold(p, b.milestone))} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setPrefs((p) => toggleFold(p, b.milestone)))}>
                      <span className="tw">▾</span><span className="bn">{milestoneName(b.milestone)}</span><span className="c">{b.tasks.length}</span>
                      <button className="hide" title="Hide this milestone" onClick={(e) => { e.stopPropagation(); setPrefs((p) => hideMilestone(p, b.milestone)); }}>hide</button>
                    </div>
                    {!b.folded && (stacksState(roles, col.id)
                      ? b.stacks.map((s) => {
                        const at = row++;
                        return <ViewportRow key={s.top.id} initial={at < 12} estimate={96} force={s.members.some((t) => t.id === spot)}>
                          {s.members.length > 1 ? <OpenStack stack={s} card={drawCard} enabled={!lift} /> : drawCard(s.top)}
                        </ViewportRow>;
                      })
                      : b.tasks.map((t) => {
                        const at = row++;
                        return <ViewportRow key={t.id} initial={at < 12} estimate={96} force={t.id === spot}>{drawCard(t)}</ViewportRow>;
                      }))}
                  </div>
                ))}
              </Viewport>
            </section>
          );
        })}
      </div>
      {lifted && (
        <div ref={ghost} className="lift">
          <Card task={lifted} now={now} names={hud.names} roles={roles} compact={compact} marks={{}} onOpen={() => {}} dismiss={() => {}} style={{ width: lift?.w }} />
        </div>
      )}
      {held && heldTask && (
        <div className="lift" style={{ left: held.rect.left, top: held.rect.top }}>
          <Card task={heldTask} now={now} names={hud.names} roles={roles} compact={compact} marks={{}} onOpen={() => {}} dismiss={() => {}} style={{ width: held.w }} />
        </div>
      )}
      {active && started.asking && (
        <StartQuestion asking={started.asking} harnesses={started.harnesses} names={hud.names} canStart={starts.canStart()} pick={(change) => starts.pick(change)}
          start={() => answer("1")} manual={() => answer("2")} cancel={() => answer("Escape")} />
      )}
      {active && (
        <ModalHost store={openTask} cards={cards} draw={(task) => {
          const taskStack = stackOf(view, task.id);
          return <Modal key={task.id} task={task} tasks={cards} records={records} open={setOpen} stack={taskStack && <StackList stack={taskStack} id={task.id} open={setOpen} />} names={hud.names} roles={roles} marks={marksOf(task.id)} now={now} capabilities={hud.capabilities}
          profiles={profilesOf(started.harnesses)} milestones={milestones.map((o) => o.value).filter(Boolean)} close={() => setOpen(null)}
          hide={() => { setPrefs((p) => hideTask(p, task.id)); setOpen(null); }} archive={() => setArchiving(task.id)} constellation={() => constellation(task.lane)}
          move={(to) => { if (!dropAsks(task, to, roles)) return void moves.drop(task, to); starts.ask(task, "modal", roles); setOpen(null); }}
          start={() => { starts.ask(task, "modal", roles); setOpen(null); }}
          dismiss={() => moves.dismiss(task.id)} dismissStart={() => starts.dismiss(task.id)}
          saved={(record) => { records.forget(task.id); setEdited((all) => ({ ...all, [task.id]: { record, source: hud.cards } })); }} />;
        }} />
      )}
      {active && archiveTask && (
        <ArchiveDialog key={archiveDialogKey(archiveTask.id)} task={archiveTask} roles={hud.roles} lane={hud.names[archiveTask.lane] ?? archiveTask.lane} close={() => setArchiving(null)}
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

/** The `hud` fields the view draws. The rest of the HUD (the clock, the DAGs, the feed) changes on most stream events and none of it is on the Kanban. */
const SHOWN = ["cards", "names", "roles", "types", "claims", "milestoneDone", "capabilities", "hint"] as const;

/** `KanbanView`, drawn again only when a field it shows or another prop changes, so an event that moves no card draws none. */
export const Kanban = memo(KanbanView, ({ hud: before, ...a }, { hud: after, ...b }) =>
  SHOWN.every((k) => before[k] === after[k]) && (Object.keys(a) as (keyof typeof a)[]).every((k) => a[k] === b[k]));
