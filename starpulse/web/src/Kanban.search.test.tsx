// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "./hud";
import type { KanbanTask } from "./kanban";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const card = (id: string, title: string, assignee: string): KanbanTask => ({
  id, title, lane: "ready", milestone: "", labels: [], assignee, dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0,
});
const cards = [card("TASK-1", "plain", "@agent-a"), card("TASK-2", "needle", "@agent-a"), card("TASK-3", "plain", "@agent-b")];
const hud = { cards, names: {}, claims: {}, boardUrl: null } as unknown as HudState;

let host: HTMLDivElement, root: Root;
const type = (input: HTMLInputElement, value: string) =>
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
const clear = () => host.querySelector<HTMLButtonElement>('button[aria-label="Clear the search"]');
const shown = () => ["TASK-1", "TASK-2", "TASK-3"].filter((id) => host.textContent?.includes(id));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/?assignee=%40agent-a");
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} />));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the Kanban search's clear button", () => {
  it("draws one ✕ only while the search holds text", () => {
    const input = host.querySelector<HTMLInputElement>("#kbq")!;

    expect(clear()).toBeNull();
    type(input, "needle");
    expect(host.querySelectorAll('button[aria-label="Clear the search"]')).toHaveLength(1);
    type(input, "");
    expect(clear()).toBeNull();
  });

  it("empties the query, keeps the focus in the input and leaves the other filters set", () => {
    const input = host.querySelector<HTMLInputElement>("#kbq")!;
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
