// @vitest-environment jsdom
import { act, useState } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskView } from "./TaskView";
import { props } from "../../tests/taskViewFixtures";

describe("editing one section at a time", () => {
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
  const stubWriter = () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ task: "TASK-9" })));
    vi.stubGlobal("fetch", fetcher);
    return fetcher;
  };
  const wrote = (fetcher: ReturnType<typeof stubWriter>) => JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  const q = <T extends Element>(host: ParentNode, selector: string) => host.querySelector<T>(selector);
  const click = (el: Element | null) => { expect(el, "element to click").toBeTruthy(); act(() => (el as HTMLElement).click()); };
  const type = (el: Element | null, value: string) => {
    expect(el, "field to type into").toBeTruthy();
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    act(() => { setter.call(el, value); el!.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const key = async (name: string, init: KeyboardEventInit = {}) => act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true, ...init })); });
  const open = (host: HTMLElement) => host.querySelectorAll(".sec.on, .tvhead .on");
  const pen = (host: HTMLElement, name: string) => q<HTMLButtonElement>(host, `button.pen[aria-label="Edit ${name}"]`);

  it("puts a ✎ Edit beside each section heading, the title and Details, and none when the board cannot edit", () => {
    const host = mount();

    for (const name of ["description", "acceptance criteria", "definition of done", "implementation plan", "notes", "title", "details"]) expect(pen(host, name), name).toBeTruthy();
    expect(q(host, ".tvhead .editbtn")).toBeNull();
    const readOnly = mount({ capabilities: { edit: false, archive: false } });
    expect(q(readOnly, "button.pen")).toBeNull();
  });

  it("opens that section's editor in place with its own bar while the rest stays readable", () => {
    const host = mount();

    click(pen(host, "description"));

    expect(open(host)).toHaveLength(1);
    const editor = q<HTMLTextAreaElement>(host, '.sec.on textarea[aria-label="Description"]');
    expect(editor?.readOnly).toBe(false);
    expect(q(host, ".sec.on")?.textContent).toContain("Ctrl+Enter saves · Esc cancels");
    expect([...host.querySelectorAll(".sec.on button")].map((b) => b.textContent)).toEqual(expect.arrayContaining(["Cancel", "Save"]));
    expect(host.textContent).toContain("1. Write the test");
    expect(pen(host, "description")).toBeNull();
    expect(pen(host, "notes")).toBeTruthy();
    expect(host.textContent).not.toContain("fields changed");
  });

  it("replaces the open editor, and drops its draft, when a second ✎ is pressed", () => {
    const host = mount();

    click(pen(host, "description"));
    type(q(host, '.sec.on textarea[aria-label="Description"]'), "a draft nobody saved");
    click(pen(host, "notes"));

    expect(open(host)).toHaveLength(1);
    expect(q(host, '.sec.on textarea[aria-label="Notes"]')).toBeTruthy();
    expect(host.textContent).not.toContain("a draft nobody saved");
    expect(host.textContent).toContain("the full description");
  });

  it("shows the description draft as Markdown on Preview and returns it on Write", () => {
    const host = mount();

    click(pen(host, "description"));
    type(q(host, '.sec.on textarea[aria-label="Description"]'), "## Heading\n\nbody text");
    click([...host.querySelectorAll<HTMLElement>('[role="tab"]')].find((t) => t.textContent === "Preview") ?? null);

    expect(q(host, ".sec.on .md h4")?.textContent).toBe("Heading");
    expect(q(host, ".sec.on textarea")).toBeNull();
    click([...host.querySelectorAll<HTMLElement>('[role="tab"]')].find((t) => t.textContent === "Write") ?? null);
    expect(q<HTMLTextAreaElement>(host, '.sec.on textarea[aria-label="Description"]')?.value).toBe("## Heading\n\nbody text");
  });

  it("adds and removes a checklist row in the editor, and Cancel restores the list", () => {
    const host = mount();

    click(pen(host, "acceptance criteria"));
    const rows = () => host.querySelectorAll(".sec.on .item textarea");
    expect(rows()).toHaveLength(2);
    click([...host.querySelectorAll<HTMLElement>(".sec.on button.add")].find((b) => b.textContent === "+ Add criterion") ?? null);
    expect(rows()).toHaveLength(3);
    type(rows()[2], "a third gate");
    click(q(host, '.sec.on button[aria-label="Remove Acceptance criteria #1"]'));
    expect([...rows()].map((r) => (r as HTMLTextAreaElement).value)).toEqual(["make lint-changed passes", "a third gate"]);
    click([...host.querySelectorAll<HTMLElement>(".sec.on button")].find((b) => b.textContent === "Cancel") ?? null);

    expect(open(host)).toHaveLength(0);
    expect(host.textContent).toContain("A Vitest test failed first");
    expect(host.textContent).not.toContain("a third gate");
  });

  it("saves only the open section on Ctrl+Enter, toasts it and reports it saved", async () => {
    const fetcher = stubWriter();
    const onSaved = vi.fn();
    const host = mount({ onSaved });

    click(pen(host, "description"));
    type(q(host, '.sec.on textarea[aria-label="Description"]'), "a better description");
    await key("Enter", { ctrlKey: true });

    expect(fetcher).toHaveBeenCalledOnce();
    expect(Object.keys(wrote(fetcher).changes)).toEqual(["description"]);
    expect(open(host)).toHaveLength(0);
    expect(q(host, ".toast")?.textContent).toBe("✓ Saved description");
    expect(host.textContent).toContain("a better description");
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ description: "a better description" }), ["description"]);
  });

  it("edits the title and Details with their own bars, Details as profile, priority and milestone selects", async () => {
    const fetcher = stubWriter();
    const host = mount({ profiles: ["@agent-standard-high", "@agent-light-low"], milestones: ["m-89", "m-90"] });

    click(pen(host, "title"));
    expect(q(host, '.tvhead textarea[aria-label="Title"]')?.hasAttribute("readonly")).toBe(false);
    expect(q(host, ".tvhead")?.textContent).toContain("Ctrl+Enter saves · Esc cancels");
    click(pen(host, "details"));
    expect(open(host)).toHaveLength(1);
    expect([...host.querySelectorAll(".sec.on select")].map((x) => x.getAttribute("aria-label"))).toEqual(["Profile", "Priority", "Milestone"]);
    const milestone = q<HTMLSelectElement>(host, '.sec.on select[aria-label="Milestone"]')!;
    act(() => { Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(milestone, "m-90"); milestone.dispatchEvent(new Event("change", { bubbles: true })); });
    await key("Enter", { ctrlKey: true });

    expect(wrote(fetcher).changes).toEqual({ milestone: "m-90" });
    expect(q(host, ".toast")?.textContent).toBe("✓ Saved details");
  });

  it("cancels the open editor on Escape, and a second Escape closes the modal", async () => {
    const close = vi.fn();
    const host = mount({ close });

    click(pen(host, "notes"));
    await key("Escape");
    expect(open(host)).toHaveLength(0);
    expect(close).not.toHaveBeenCalled();
    await key("Escape");
    expect(close).toHaveBeenCalledOnce();
  });

  it("closes on Escape when an earlier key listener redraws its host, handing it a new close, before it hears the key", async () => {
    const close = vi.fn();
    let redraw = () => {};
    function Host() {
      const [n, setN] = useState(0);
      // oxlint-disable-next-line react/globals -- the test hands the host's redraw out to a key listener
      redraw = () => flushSync(() => setN(n + 1));
      return <TaskView {...props({ close: () => close(n) })} />;
    }
    const redrawFirst = () => redraw();
    addEventListener("keydown", redrawFirst);
    try {
      const host = document.body.appendChild(document.createElement("div"));
      const root = createRoot(host);
      act(() => root.render(<Host />));
      mounted.push({ root, host });

      await key("Escape");

      expect(close).toHaveBeenCalledOnce();
    } finally {
      removeEventListener("keydown", redrawFirst);
    }
  });

  it("toggles a Definition of done checkbox straight to a write, with no editor", async () => {
    const fetcher = stubWriter();
    const host = mount();

    const box = q<HTMLInputElement>(host, 'input[aria-label="Definition of done #1 done"]');
    expect(box?.disabled).toBe(false);
    await act(async () => { box!.click(); });

    expect(open(host)).toHaveLength(0);
    expect(Object.keys(wrote(fetcher).changes)).toEqual(["definitionOfDone"]);
    expect(q(host, ".toast")?.textContent).toBe("✓ Saved definition of done");
  });

  it("opens an evidence field under a newly checked criterion and writes it on Ctrl+Enter, or nothing on Escape", async () => {
    const fetcher = stubWriter();
    const host = mount();

    act(() => q<HTMLInputElement>(host, 'input[aria-label="Acceptance criteria #2 done"]')!.click());
    expect(fetcher).not.toHaveBeenCalled();
    const field = q<HTMLTextAreaElement>(host, ".sec.on .evidence textarea");
    expect(field).toBeTruthy();
    await key("Escape");
    expect(q(host, ".evidence")).toBeNull();
    expect(q<HTMLInputElement>(host, 'input[aria-label="Acceptance criteria #2 done"]')?.checked).toBe(false);

    act(() => q<HTMLInputElement>(host, 'input[aria-label="Acceptance criteria #2 done"]')!.click());
    type(q(host, ".sec.on .evidence textarea"), "lint passed on the head commit");
    await key("Enter", { ctrlKey: true });

    expect(wrote(fetcher).comment).toBe("AC #2: lint passed on the head commit");
    expect(Object.keys(wrote(fetcher).changes)).toEqual(["acceptanceCriteria"]);
  });
});
