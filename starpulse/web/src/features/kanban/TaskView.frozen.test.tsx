// @vitest-environment jsdom
// The task view offers Freeze on a live task and Unfreeze on a frozen one, and says who froze it and why.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TaskView } from "./TaskView";
import { props, task } from "../../tests/taskViewFixtures";

const frozen = { at: "2026-11-25T20:00:00Z", by: "operator", reason: "PR 10702 merged mid-rework" };

let host: HTMLDivElement, root: Root;
const show = (over: Partial<Parameters<typeof TaskView>[0]>) => act(() => root.render(<TaskView {...props(over)} />));
const button = (text: string) => [...host.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.startsWith(text));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the task view's freeze control", () => {
  it("offers Freeze on a live task and sends the typed reason", () => {
    const freeze = vi.fn();
    show({ freeze });

    expect(button("Unfreeze")).toBeUndefined();
    act(() => button("Freeze…")!.click());
    const input = host.querySelector<HTMLInputElement>('input[aria-label="Reason for freezing"]')!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "waiting on a rework");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => button("Freeze")!.click());

    expect(freeze).toHaveBeenCalledWith("waiting on a rework");
  });

  it("offers Unfreeze on a frozen task, names who and why, and sends null", () => {
    const freeze = vi.fn();
    show({ freeze, task: { ...task, frozen } });

    expect(button("Freeze…")).toBeUndefined();
    expect(host.querySelector(".frozenote")?.textContent).toContain("operator");
    expect(host.querySelector(".frozenote")?.textContent).toContain("PR 10702 merged mid-rework");
    act(() => button("Unfreeze")!.click());

    expect(freeze).toHaveBeenCalledWith(null);
  });

  it("shows no control where the view has no freeze handler", () => {
    show({});

    expect(button("Freeze")).toBeUndefined();
  });
});
