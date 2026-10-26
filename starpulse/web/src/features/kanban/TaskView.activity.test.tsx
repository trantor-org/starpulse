// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskView } from "./TaskView";
import { props, record, task } from "../../tests/taskViewFixtures";

describe("the task view's Activity and Comments sections", () => {
  const mounted: { root: ReturnType<typeof createRoot>; host: HTMLElement }[] = [];
  const mount = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => {
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    act(() => root.render(<TaskView {...props(over)} />));
    mounted.push({ root, host });
    return host;
  };
  afterEach(() => {
    for (const { root, host } of mounted.splice(0)) { act(() => root.unmount()); host.remove(); }
    vi.unstubAllGlobals();
  });
  const q = <T extends Element>(host: ParentNode, selector: string) => host.querySelector<T>(selector);
  const typeInto = (field: HTMLTextAreaElement, value: string) => {
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(field, value);
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
  };
  const machines = [
    { machine: "in-progress", state: "pr_opened", at: 300, trail: [{ event: "AC_CHECKPOINTED", state: "in_progress", at: 200 }, { event: "PR_OPENED", state: "pr_opened", at: 300 }] },
    { machine: "ci", state: "green", at: 250, trail: [{ event: "CI_PASSED", state: "green", at: 250 }] },
  ];

  it("activity draws every recorded event oldest first, with no checkbox, button or select inside it", () => {
    const host = mount({ task: { ...task, machines } });
    const activity = q<HTMLElement>(host, "#activity");

    expect(activity?.textContent).toContain("AC_CHECKPOINTED");
    expect(activity?.textContent).toContain("CI_PASSED");
    expect(activity?.textContent).toContain("PR_OPENED");
    expect(activity?.textContent?.indexOf("AC_CHECKPOINTED")).toBeLessThan(activity?.textContent?.indexOf("PR_OPENED") ?? 0);
    expect(activity?.querySelectorAll("input, button, select")).toHaveLength(0);
    expect(activity?.querySelectorAll(".ev[data-kind=checkpoint]")).toHaveLength(1);
  });

  it("comment posts an edit carrying the comment and writes no field", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ task: "TASK-9" })));
    vi.stubGlobal("fetch", fetcher);
    const host = mount({ record: { ...record, comments: [] } });
    typeInto(q<HTMLTextAreaElement>(host, "#comments textarea")!, "ship it");

    await act(async () => { q<HTMLButtonElement>(host, "#comments .compose button")!.click(); });

    const body = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
    expect(fetcher.mock.calls[0][0]).toBe("/api/edit");
    expect(body).toMatchObject({ task: task.id, comment: "ship it", changes: { title: record.title }, base: { title: record.title } });
  });

  it("comment draws the task's comments under Comments, never under Activity", () => {
    const host = mount({ record: { ...record, comments: [{ created: "2026-10-26 10:00", text: "looks good" }] } });

    expect(q<HTMLElement>(host, "#comments")?.textContent).toContain("looks good");
    expect(q<HTMLElement>(host, "#activity")?.textContent).not.toContain("looks good");
  });
});
