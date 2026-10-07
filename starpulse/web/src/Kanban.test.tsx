import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { Card, HeldBy, StackList, StackView, Stacks } from "./Kanban";
import { CLOSED, NO_PREFS, layout, stackOf, stackStep, stacksOf, type KanbanTask, type StackEvent } from "./kanban";
import { place } from "./move";
import { TaskView } from "./TaskView";

const task: KanbanTask = {
  id: "PROJ-1", title: "A title long enough to need two lines in a comfortable card", lane: "in_progress", milestone: "m-1", labels: ["feature", "needs-human"], assignee: "@agent-standard-high",
  dependencies: [], openDeps: 2, prs: [], description: "", live: { machine: "in-progress", state: "red_proven", at: 100 }, released: false, moves: {}, entered: 0,
};
const draw = (compact: boolean) => renderToStaticMarkup(<Card task={task} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} compact={compact} />);

describe("a Kanban card's density", () => {
  it("keeps the footer of labels, dependencies and profile when comfortable", () => {
    const html = draw(false);

    expect(html).toContain('class="foot"');
    expect(html).toContain("needs-human");
    expect(html).toContain("standard-high");
    expect(html).not.toContain("compact");
  });

  it("drops the footer but keeps the id, title and machine line when compact", () => {
    const html = draw(true);

    expect(html).toContain('class="card compact"');
    expect(html).not.toContain('class="foot"');
    expect(html).not.toContain("needs-human");
    expect(html).toContain("PROJ-1");
    expect(html).toContain("A title long enough");
    expect(html).toContain("red proven");
    expect(html).toContain("1m");
  });
});

describe("what holds the Waiting lane", () => {
  const holder = (id: string, holds: number, labels: string[] = []) => ({ task: { ...task, id, labels }, holds });

  it("marks a card with the Waiting tasks it holds, and draws no mark on a card that holds none", () => {
    const held = renderToStaticMarkup(<Card task={task} holds={23} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} />);
    const free = renderToStaticMarkup(<Card task={task} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} />);

    expect(held).toContain('title="holds 23 Waiting tasks"');
    expect(held).toContain("⛓23");
    expect(free).not.toContain("⛓");
  });

  it("lists the top three holders with their counts, flags a needs-human one and counts the rest", () => {
    const html = renderToStaticMarkup(
      <HeldBy holders={[holder("TASK-2706", 23, ["needs-human"]), holder("TASK-2875", 3), holder("TASK-2873", 3), holder("TASK-1878", 2)]} open={() => {}} />,
    );

    expect(html).toContain("Held by");
    expect(html).toMatch(/TASK-2706.*23/);
    expect(html).toContain('class="hb nh"');
    expect(html).toContain("TASK-2873");
    expect(html).not.toContain("TASK-1878");
    expect(html).toContain("+1 more");
  });

  it("marks a card's place in the hovered chain, and leaves a card outside it as it was", () => {
    const as = (chain?: "self" | "holds" | "waits") =>
      renderToStaticMarkup(<Card task={task} chain={chain} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} />);

    expect(as("self")).toContain('class="card chain-self"');
    expect(as("holds")).toContain('class="card chain-holds"');
    expect(as("waits")).toContain('class="card chain-waits"');
    expect(as()).toContain('class="card"');
  });

  it("draws nothing when no task holds Waiting work", () => {
    expect(renderToStaticMarkup(<HeldBy holders={[]} open={() => {}} />)).toBe("");
  });
});

describe("a Kanban card's start control", () => {
  type El = ReactElement<{ children?: ReactNode; className?: string; onClick?: (e: unknown) => void; disabled?: boolean; title?: string }>;
  const ready = (allowed = true): KanbanTask => ({ ...task, lane: "ready", moves: { in_progress: { allowed, reason: allowed ? "" : "needs an Implementation Plan", skill: "" } } });
  const card = (t: KanbanTask, onOpen = () => {}, onPlay = () => {}) =>
    Card({ task: t, now: 160, marks: {}, names: {}, onOpen, onPlay, dismiss: () => {} }) as El;
  const kids = (el: El) => [el.props.children].flat(Infinity).filter(isValidElement) as El[];
  const play = (el: El) => kids(el).find((k) => k.type === "button" && /\bplay\b/.test(k.props.className ?? ""));
  const click = () => ({ stopPropagation: vi.fn() });

  it("draws the start control as the right-edge strip beside the card body, not beside the id", () => {
    const root = card(ready());
    const top = kids(root).find((k) => k.props.className === "top")!;

    expect(play(root)?.props.className).toBe("play edge");
    expect(play(top)).toBeUndefined();
    expect(renderToStaticMarkup(root)).toContain('aria-label="Start PROJ-1"');
  });

  it("asks the start question on a click of the strip without opening the card", () => {
    const onOpen = vi.fn(), onPlay = vi.fn(), e = click();

    const strip = play(card(ready(), onOpen, onPlay));
    expect(strip).toBeDefined();
    strip!.props.onClick!(e);

    expect(onPlay).toHaveBeenCalledOnce();
    expect(e.stopPropagation).toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("opens the task on a click of the card beside the strip", () => {
    const onOpen = vi.fn(), onPlay = vi.fn();

    card(ready(), onOpen, onPlay).props.onClick!(click());

    expect(onOpen).toHaveBeenCalledOnce();
    expect(onPlay).not.toHaveBeenCalled();
  });

  it("disables the strip with the guard's reason as its title while a guard refuses the move", () => {
    const strip = play(card(ready(false)));

    expect(strip).toBeDefined();
    expect(strip!.props.disabled).toBe(true);
    expect(strip!.props.title).toBe("needs an Implementation Plan");
  });

  it("draws no strip on a card in a lane a session does not start from", () => {
    expect(play(card({ ...ready(), lane: "in_progress" }))).toBeUndefined();
  });
});

describe("a Waiting stack", () => {
  const wait = (id: string, ...dependencies: string[]): KanbanTask => ({ ...task, id, title: `Title of ${id}`, lane: "waiting", dependencies, openDeps: dependencies.length, live: null });
  const chain = [wait("T-1"), wait("T-2", "T-1"), wait("T-3", "T-2")];
  const stack = stacksOf(chain)[0];
  const card = (t: KanbanTask, extra: { under?: boolean; stacked?: number; links?: string[] } = {}) =>
    <Card key={t.id} task={t} holds={t.id === "T-1" ? 2 : undefined} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} {...extra} />;
  type Root = ReactElement<{ onPointerEnter: () => void; onPointerLeave: () => void; onFocus: () => void; onBlur: (e: unknown) => void; onKeyDown: (e: { key: string }) => void }>;
  /** The stack drawn from its state, with the events it raises applied to that state, as the Kanban's stack does. */
  const drive = () => {
    let state = CLOSED;
    const root = () => StackView({ stack, state, card, onEvent: (e: StackEvent) => (state = stackStep(state, e)) }) as Root;
    return { root, html: () => renderToStaticMarkup(root()) };
  };

  it("folds to its top card whole, with a count badge beside the ⛓ and one or two card edges peeking below", () => {
    const html = drive().html();

    expect(html).toContain('class="stack"');
    expect(html).toMatch(/data-id="T-1"/);
    expect(html).toMatch(/class="sk"[^>]*>.*?2<\/span><span class="holds"[^>]*>⛓2/);
    expect(html.match(/class="edge"/g)).toHaveLength(2);
    expect(renderToStaticMarkup(<StackView stack={stacksOf(chain.slice(0, 2))[0]} state={CLOSED} card={card} onEvent={() => {}} />).match(/class="edge"/g)).toHaveLength(1);
    expect(html).not.toContain("waits on");
  });

  it("unstacks on hover, each card below the top saying what it waits on, and folds when the pointer leaves", () => {
    const d = drive();
    d.root().props.onPointerEnter();

    expect(d.html()).toContain('class="stack open"');
    expect(d.html()).toContain("⧗ waits on</span> <span class=\"nw\">T-1</span>");
    expect(d.html()).toContain("⧗ waits on</span> <span class=\"nw\">T-2</span>");

    d.root().props.onPointerLeave();

    expect(d.html()).toContain('class="stack"');
    expect(d.html()).not.toContain("waits on");
  });

  it("unstacks on focus and folds when focus leaves the stack, not when it moves between its cards", () => {
    const d = drive();
    d.root().props.onFocus();
    expect(d.html()).toContain("⧗ waits on");

    d.root().props.onBlur({ currentTarget: { contains: () => true }, relatedTarget: {} });
    expect(d.html()).toContain("⧗ waits on");

    d.root().props.onBlur({ currentTarget: { contains: () => false }, relatedTarget: null });
    expect(d.html()).not.toContain("⧗ waits on");
  });

  it("folds on Escape even with the pointer still over it, and ignores any other key", () => {
    const d = drive();
    d.root().props.onPointerEnter();
    d.root().props.onFocus();

    d.root().props.onKeyDown({ key: "ArrowDown" });
    expect(d.html()).toContain("⧗ waits on");

    d.root().props.onKeyDown({ key: "Escape" });
    expect(d.html()).not.toContain("⧗ waits on");
  });

  it("lists the stack in the task modal, the open task in bold and the others as buttons that open them", () => {
    const html = renderToStaticMarkup(<StackList stack={stack} id="T-2" open={() => {}} />);

    expect(html).toMatch(/▣ <button[^>]*>T-1<\/button>/);
    expect(html).toMatch(/↳ <b>T-2<\/b>/);
    expect(html).toMatch(/↳ <button[^>]*>T-3<\/button>/);
  });

  it("re-forms when a drag moves a stacked task out of Waiting, so the badge and its cards go with it", () => {
    const draw = (tasks: KanbanTask[]) => renderToStaticMarkup(
      <>{layout(tasks, { waiting: "Waiting" }, NO_PREFS).columns.find((c) => c.id === "waiting")!.buckets.map((b) => <Stacks key={b.milestone} stacks={b.stacks} card={card} enabled />)}</>,
    );
    const moved = place(chain, { pending: { "T-2": { from: "waiting", to: "ready", saving: true, at: 1 } }, refused: {} });

    expect(draw(chain)).toContain('class="stack"');
    expect(stackOf(layout(chain, {}, NO_PREFS), "T-3")?.members).toHaveLength(3);
    const after = draw(moved);
    expect(after).not.toContain('class="stack"');
    expect(after).not.toContain('class="sk"');
    expect(after).not.toContain("T-2");
    expect(after).toContain('data-id="T-1"');
    expect(after).toContain('data-id="T-3"');
  });
});

describe("a Done chain", () => {
  const fin = (id: string, ...dependencies: string[]): KanbanTask => ({ ...task, id, title: `Title of ${id}`, lane: "done", dependencies, openDeps: 0, live: null });
  const chain = [fin("T-1"), fin("T-2", "T-1"), fin("T-3", "T-2")];
  const stack = stacksOf(chain, "done")[0];
  const card = (t: KanbanTask, extra: { under?: boolean; stacked?: number; links?: string[] } = {}) =>
    <Card key={t.id} task={t} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} {...extra} />;
  type Root = ReactElement<{ onPointerEnter: () => void; onPointerLeave: () => void }>;
  const drive = () => {
    let state = CLOSED;
    const root = () => StackView({ stack, state, card, onEvent: (e: StackEvent) => (state = stackStep(state, e)) }) as Root;
    return { root, html: () => renderToStaticMarkup(root()) };
  };

  it("folds to the chain's last finished task with a green count badge", () => {
    const html = drive().html();

    expect(html).toMatch(/data-id="T-3"/);
    expect(html).toMatch(/class="sk dn"[^>]*title="2 Done tasks this one&#x27;s chain finished first; hover to unstack"/);
    expect(html).not.toContain("unblocked");
  });

  it("draws the Waiting badge without the green on a Waiting stack's top", () => {
    const html = renderToStaticMarkup(<Card task={{ ...task, lane: "waiting" }} stacked={2} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} />);

    expect(html).toContain('class="sk"');
    expect(html).not.toContain("sk dn");
  });

  it("unstacks on hover, each card below the top saying which task it unblocked, and folds when the pointer leaves", () => {
    const d = drive();
    d.root().props.onPointerEnter();

    expect(d.html()).toContain('class="stack open"');
    expect(d.html()).toContain('✓ unblocked</span> <span class="nw">T-3</span>');
    expect(d.html()).toContain('✓ unblocked</span> <span class="nw">T-2</span>');
    expect(d.html()).not.toContain("waits on");

    d.root().props.onPointerLeave();

    expect(d.html()).toContain('class="stack"');
    expect(d.html()).not.toContain("unblocked");
  });

  it("labels the task modal's stack section done chain, and a Waiting stack's waiting stack", () => {
    const draw = (lane: string) => renderToStaticMarkup(
      <TaskView task={{ ...task, lane }} record={null} lane="" machine="—" profiles={[]} milestones={[]} refusal={null} startNote={null} capabilities={undefined}
        saving={false} claiming={false} close={() => {}} hide={() => {}} constellation={() => {}} move={() => {}} start={() => {}}
        stack={<StackList stack={stack} id="T-2" open={() => {}} />} />,
    );

    expect(draw("done")).toMatch(/<td>done chain<\/td><td class="stacklist"><div>▣ <button[^>]*>T-3<\/button><\/div><div>↳ <b>T-2<\/b>/);
    expect(draw("waiting")).toContain("<td>waiting stack</td>");
describe("a Waiting card linked to a blocker in another milestone", () => {
  type El = ReactElement<{ children?: ReactNode; className?: string; title?: string; onClick?: (e: unknown) => void; onPointerDown?: (e: unknown) => void; onKeyDown?: (e: unknown) => void }>;
  const blocker: KanbanTask = { ...task, id: "T-1", milestone: "m-1", lane: "waiting" };
  const waiting: KanbanTask = { ...task, id: "T-2", milestone: "m-2", lane: "waiting", dependencies: ["T-1"], openDeps: 1 };
  const card = (onOpen = () => {}, onCross = () => {}, cross: KanbanTask[] = [blocker]) =>
    Card({ task: waiting, now: 160, marks: {}, names: {}, onOpen, dismiss: () => {}, cross, onCross }) as El;
  const walk = (el: El): El[] => [el, ...[el.props.children].flat(Infinity).filter(isValidElement).flatMap((k) => walk(k as El))];
  const badge = (el: El) => walk(el).find((k) => /\bxm\b/.test(k.props.className ?? ""));
  const ev = () => ({ stopPropagation: vi.fn(), key: "Enter", preventDefault: vi.fn() });

  it("draws a badge in the footer naming the blocker's milestone and id, and none on a card with no blocker elsewhere", () => {
    const html = renderToStaticMarkup(card());

    expect(html).toMatch(/<button[^>]*class="xm"[^>]*>↗ <span class="nw">m-1<\/span> · <span class="nw">T-1<\/span><\/button>/);
    expect(html).toContain("Waits on T-1 in m-1");
    expect(badge(card(() => {}, () => {}, []))).toBeUndefined();
    expect(renderToStaticMarkup(<Card task={waiting} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} />)).not.toContain("↗");
  });

  it("opens the blocker's task on a click of the badge, without opening the card or starting a drag", () => {
    const onOpen = vi.fn(), onCross = vi.fn(), click = ev(), press = ev();

    const xm = badge(card(onOpen, onCross))!;
    xm.props.onPointerDown!(press);
    xm.props.onClick!(click);

    expect(onCross).toHaveBeenCalledExactlyOnceWith("T-1");
    expect(click.stopPropagation).toHaveBeenCalled();
    expect(press.stopPropagation).toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("keeps Enter and Space on the badge from opening the card", () => {
    const key = ev();

    badge(card())!.props.onKeyDown!(key);

    expect(key.stopPropagation).toHaveBeenCalled();
  });

  it("draws a badge per blocker, and names a blocker with no milestone", () => {
    const html = renderToStaticMarkup(card(() => {}, () => {}, [blocker, { ...blocker, id: "T-9", milestone: "" }]));

    expect(html.match(/class="xm"/g)).toHaveLength(2);
    expect(html).toContain("no milestone");
  });

  it("is left off a compact card, which drops the footer", () => {
    expect(renderToStaticMarkup(<Card task={waiting} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} cross={[blocker]} compact />)).not.toContain("↗");
  });
});
