// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "./hud";
import type { KanbanTask } from "./kanban";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const card = (id: string, title: string, assignee: string, labels: string[] = []): KanbanTask => ({
  id, title, lane: "ready", milestone: "", labels, assignee, dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0,
});
const cards = [card("TASK-1", "plain", "@agent-a"), card("TASK-2", "needle", "@agent-a", ["backup"]), card("TASK-3", "plain", "@agent-b")];
const hud = { cards, names: {}, claims: {}, boardUrl: null } as unknown as HudState;

let host: HTMLDivElement, slot: HTMLDivElement, root: Root;
let queries: string[];
const type = (input: HTMLInputElement, value: string) =>
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
const clear = () => slot.querySelector<HTMLButtonElement>('button[aria-label="Clear the search"]');
const shown = () => ["TASK-1", "TASK-2", "TASK-3"].filter((id) => host.textContent?.includes(id));

/** The Kanban over the navigator's search slot, which App draws beside it. */
const mount = () => {
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={slot} outlineSlot={null} onQuery={(q) => queries.push(q)} />));
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/?assignee=%40agent-a");
  queries = [];
  slot = document.body.appendChild(document.createElement("div"));
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  mount();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  slot.remove();
});

describe("the Kanban search's clear button", () => {
  it("draws one ✕ only while the search holds text", () => {
    const input = slot.querySelector<HTMLInputElement>("#kbq")!;

    expect(clear()).toBeNull();
    type(input, "needle");
    expect(slot.querySelectorAll('button[aria-label="Clear the search"]')).toHaveLength(1);
    type(input, "");
    expect(clear()).toBeNull();
  });

  it("empties the query, keeps the focus in the input and leaves the other filters set", () => {
    const input = slot.querySelector<HTMLInputElement>("#kbq")!;
    type(input, "needle");
    expect(shown()).toEqual(["TASK-2"]);

    const press = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    act(() => void clear()!.dispatchEvent(press));
    act(() => clear()!.click());

    expect(press.defaultPrevented).toBe(true);
    expect(input.value).toBe("");
    expect(document.activeElement).toBe(input);
    expect(shown()).toEqual(["TASK-1", "TASK-2"]);
    expect(clear()).toBeNull();
  });
});

describe("the Kanban search in the navigator's slot", () => {
  it("draws in the slot, not the toolbar, which keeps Assignee, Milestone, clear and Hidden", () => {
    act(() => root.unmount());
    root = createRoot(host);
    history.replaceState(null, "", "/");
    localStorage.setItem("fv.kanban.prefs", JSON.stringify({ query: "", assignee: "@agent-a", milestone: null, folded: [], hiddenMilestones: [], hiddenTasks: ["TASK-3"] }));
    mount();

    expect(slot.querySelector("#kbq")).not.toBeNull();
    expect(host.querySelector("#kbq")).toBeNull();
    const toolbar = host.querySelector(".filters")!.textContent;
    for (const part of ["Assignee", "Milestone", "clear", "Hidden:"]) expect(toolbar).toContain(part);
  });

  it("filters the columns as the query is typed and offers label suggestions under the input", () => {
    const input = slot.querySelector<HTMLInputElement>("#kbq")!;
    act(() => input.focus());
    type(input, "back");

    const options = [...slot.querySelectorAll<HTMLButtonElement>('[role="listbox"] [role="option"]')];
    expect(options.map((o) => o.textContent)).toEqual(["backup1"]);
    act(() => options[0].click());

    expect(input.value).toBe("label:backup ");
    expect(shown()).toEqual(["TASK-2"]);
  });

  it("reports its query, so the navigator can show whether the search holds one", () => {
    type(slot.querySelector<HTMLInputElement>("#kbq")!, "needle");
    expect(queries.at(-1)).toBe("needle");

    act(() => clear()!.click());
    expect(queries.at(-1)).toBe("");
  });
});
