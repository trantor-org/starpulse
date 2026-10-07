import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { Card, HeldBy } from "./Kanban";
import type { KanbanTask } from "./kanban";

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
