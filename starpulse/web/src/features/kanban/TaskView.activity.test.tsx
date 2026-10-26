// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskView } from "./TaskView";
import { props, record, task, stubWrites } from "../../tests/taskViewFixtures";

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
  const checked = Date.parse("2026-10-26T10:28") / 1000;
  const machines = [
    { machine: "deliver", state: "pr_opened", at: checked + 60, trail: [{ event: "AC_CHECKPOINTED", state: "start", at: checked }, { event: "PR_OPENED", state: "pr_opened", at: checked + 60 }] },
    { machine: "harness", state: "active", at: checked + 1, trail: [{ event: "TOOL_USED", state: "active", at: checked + 1 }] },
  ];
  const evidence = { created: "2026-10-26 10:28", author: "agent", text: "Verified AC #1: `vitest` failed, then passed" };

  it("activity draws checkpoint evidence and lifecycle steps oldest first, with no checkbox, button or select inside it", () => {
    const host = mount({ task: { ...task, machines }, record: { ...record, comments: [evidence] } });
    const activity = q<HTMLElement>(host, "#activity")!;
    const rows = [...activity.querySelectorAll<HTMLElement>(".ev")];

    expect(rows.map((row) => row.dataset.kind)).toEqual(["checkpoint", "system"]);
    expect(rows[0].querySelector(".tag")?.textContent).toBe("AC #1");
    expect(rows[0].querySelector(".bd code")?.textContent).toBe("vitest");
    expect(rows[1].textContent).toContain("PR_OPENED");
    expect(activity.textContent).not.toContain("TOOL_USED");
    expect(activity.querySelectorAll("input, button, select")).toHaveLength(0);
  });

  it("activity folds a checkpoint's command output under its one-line evidence", () => {
    const run = { ...evidence, text: "Verified AC #1: `vitest` exited 0\n\n```\nTests  3 passed\n```" };
    const host = mount({ record: { ...record, comments: [run] } });
    const row = q<HTMLElement>(host, "#activity .ev")!;

    expect(row.querySelector(".bd")?.textContent).toBe("vitest exited 0");
    expect(row.querySelector("details:not([open]) pre")?.textContent).toBe("Tests  3 passed");
  });

  it("a checkpoint's AC tag scrolls to its criterion and flashes it", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const host = mount({ record: { ...record, comments: [evidence] } });

    act(() => { q<HTMLAnchorElement>(host, "#activity .tag")!.click(); });

    const criterion = q<HTMLElement>(host, "#ac1")!;
    expect(scroll.mock.contexts[0]).toBe(criterion);
    expect(criterion.classList).toContain("flash");
  });

  it("comment posts an edit carrying the comment and writes no field", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ task: "TASK-9" })));
    stubWrites(fetcher);
    const host = mount({ record: { ...record, comments: [] } });
    typeInto(q<HTMLTextAreaElement>(host, "#comments textarea")!, "ship it");

    await act(async () => { q<HTMLButtonElement>(host, "#comments .compose button")!.click(); });

    const body = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
    expect(fetcher.mock.calls[0][0]).toBe("/api/edit");
    expect(body).toMatchObject({ task: task.id, comment: "ship it", changes: { title: record.title }, base: { title: record.title } });
  });

  it("comment draws the task's comments under Comments, never under Activity, and checkpoint evidence never under Comments", () => {
    const host = mount({ record: { ...record, comments: [evidence, { created: "2026-10-26 10:00", author: "Adin", text: "looks good" }] } });

    expect(q<HTMLElement>(host, "#comments")?.textContent).toContain("looks good");
    expect(q<HTMLElement>(host, "#comments")?.textContent).not.toContain("failed, then passed");
    expect(q<HTMLElement>(host, "#activity")?.textContent).not.toContain("looks good");
  });
});
