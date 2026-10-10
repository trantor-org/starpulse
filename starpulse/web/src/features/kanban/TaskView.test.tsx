// @vitest-environment jsdom
// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
// @ts-expect-error Same Node-only import: jsdom swaps the global URL for one readFileSync refuses.
import { URL as NodeURL } from "node:url";
import { act, Profiler, useState } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanban";
import { TaskView } from "./TaskView";
import { closesOnKey, copyText, copyToClipboard, menuKey, onScrim, type StartCriterion, type TaskRecord } from "./taskView";

const styles = readFileSync(new NodeURL("../../style.css", import.meta.url), "utf8");

const task: KanbanTask = {
  id: "TASK-9", title: "Redraw the view", lane: "ready", milestone: "m-89", labels: ["needs-human"], assignee: "@agent-standard-high",
  dependencies: ["TASK-1"], openDeps: 0, prs: [{ number: 12, url: "http://pr/12", checks: "pass", merged: false, merge_sha: null, merged_at: null, threads: 0, behind_main: null, stale: false }],
  description: "from the snapshot", live: null, released: false, entered: 700, created: 100, workableSince: null,
  machines: [{ machine: "in-progress", state: "pr_opened", at: 900, trail: [] }],
  moves: { in_progress: { allowed: true, reason: "", skill: "" }, review: { allowed: false, reason: "no review yet", skill: "completing-tasks" } },
};
const record: TaskRecord = {
  title: "Redraw the view", profile: "@agent-standard-high", priority: "High", labels: ["needs-human"], milestone: "m-89", dependencies: ["TASK-1"],
  description: "the full description", plan: "1. Write the test\n2. Make it pass", notes: "Checked against the live config",
  acceptanceCriteria: [{ n: 1, text: "A Vitest test failed first", checked: true }, { n: 2, text: "make lint-changed passes", checked: false }],
  definitionOfDone: [{ n: 1, text: "The completing-tasks skill was invoked", checked: false }],
  session: "",
};
const card = (id: string, lane: string, over: Partial<KanbanTask> = {}): KanbanTask => ({ ...task, id, title: `title ${id}`, lane, dependencies: [], prs: [], machines: [], ...over });
const board = [card("TASK-1", "done"), task];
const props = (over: Partial<Parameters<typeof TaskView>[0]> = {}): Parameters<typeof TaskView>[0] => ({
  task, record, lane: "Ready", now: 1000, tasks: board, open: () => {}, profiles: [], milestones: [], refusal: null, startNote: null,
  names: { ready: "Ready", done: "Done", review: "Review" }, capabilities: { edit: true, archive: true }, saving: false, claiming: false,
  close: () => {}, hide: () => {}, constellation: () => {}, move: () => {}, start: () => {}, ...over,
});
const draw = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => renderToStaticMarkup(<TaskView {...props(over)} />);
const railOf = (html: string) => html.slice(html.indexOf('class="tvcol tvrail"'));
const headings = (html: string) => [...railOf(html).matchAll(/<span class="t">([^<]+)<\/span>/g)].map((m) => m[1]);

const headOf = (html: string) => html.slice(html.indexOf('class="tvhead"'), html.indexOf('class="tvbody"'));
const lanes = (lane: string, over: Partial<KanbanTask> = {}) => ({ task: { ...task, lane, ...over }, lane });

describe("the task view in read mode", () => {
  it("draws the plan, notes and checks the record carries", () => {
    const html = draw();

    expect(html).toContain("1. Write the test");
    expect(html).toContain("Checked against the live config");
    expect(html).toContain("A Vitest test failed first");
    expect(html).toContain("The completing-tasks skill was invoked");
    expect(html).toContain("1/2");
  });

  it("frames the title, locked against input, draws the details as plain text and the long text unframed", () => {
    const html = draw();
    const framed = html.match(/class="fv[ "][^>]*>/g) ?? [];

    expect(framed).toHaveLength(1);
    expect(html.match(/<textarea[^>]*data-field="title"[^>]*>/)![0]).toContain('readOnly=""');
    expect(railOf(html)).not.toMatch(/<(select|textarea)/);
    expect(html).not.toMatch(/<textarea[^>]*data-field="(description|plan|notes)"/);
    expect(html).not.toMatch(/<input[^>]*type="checkbox"[^>]*disabled=""/);
    expect(draw({ capabilities: { edit: false, archive: false } })).toMatch(/<input[^>]*type="checkbox"[^>]*disabled=""/);
  });

  it("draws Edit and Archive only when the board can", () => {
    expect(draw()).toContain("Archive…");
    expect(draw()).toContain("Edit");
    const readOnly = draw({ capabilities: { edit: false, archive: false } });
    expect(readOnly).not.toContain("Archive…");
    expect(readOnly).not.toContain("Edit");
    expect(draw({ capabilities: undefined })).not.toContain("Archive…");
  });

  it("selects the priority's own option when the board stores it in lower case", () => {
    const html = draw({ record: { ...record, priority: "high" }, initialEditing: "details" });

    expect(html).toContain('<option value="High" selected="">High</option>');
    expect(html).not.toContain('<option value="high"');
  });

  it("falls back to the snapshot's fields until the record arrives", () => {
    const html = draw({ record: null });

    expect(html).toContain("from the snapshot");
    expect(html).not.toContain("Implementation plan");
  });
});

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

describe("the task view's header", () => {
  it("draws the id, Copy, lane, Open in Star Map and the actions in one row, with the title below", () => {
    const head = headOf(draw());
    const at = (text: string) => head.indexOf(text);

    for (const text of ["TASK-9", "Copy", ">Ready<", "Open in Star Map ↗", "▶ Start session", "Move to", "Hide task", "Archive…", 'aria-label="Close"']) expect(at(text), text).toBeGreaterThan(-1);
    const order = ["TASK-9", "Copy", ">Ready<", "Open in Star Map ↗", "▶ Start session", "Move to", "Hide task", "Archive…", 'aria-label="Close"'].map(at);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(at('data-field="title"')).toBeGreaterThan(at('aria-label="Close"'));
    expect(draw()).not.toContain('class="tvfoot"');
    // a <header> inside the board matches `#kb header`, which would centre the row and set the title in capitals
    expect(draw()).not.toMatch(/<header/);
  });

  it("offers Start session only from Ready, Waiting and Needs attention while no start is in flight", () => {
    for (const lane of ["ready", "waiting", "needs_attention"]) expect(headOf(draw(lanes(lane)))).toContain("▶ Start session");
    for (const lane of ["in_progress", "review", "done"]) expect(headOf(draw(lanes(lane)))).not.toContain("▶ Start session");
    expect(headOf(draw({ claiming: true }))).not.toContain("▶ Start session");
  });

  it("draws the Move to menu with a row per column the task has a verdict for", () => {
    const head = headOf(draw());

    expect(head).toContain('aria-haspopup="menu"');
    expect(head.match(/role="menuitem"/g)).toHaveLength(2);
    expect(head).toContain("no review yet");
    expect(head).toMatch(/class="mvmenu"[^>]*hidden=""/);
  });

  it("moves the task on the menu's Enter and closes the menu on Escape without closing the task", () => {
    expect(menuKey({ open: true, on: 1 }, "Enter", [true, true])).toEqual({ state: { open: false, on: -1 }, pick: 1, handled: true });
    expect(menuKey({ open: true, on: 0 }, "Escape", [true, true])).toMatchObject({ pick: null, handled: true, state: { open: false } });
  });

  it("copies 'TASK-N title' to the clipboard", async () => {
    const writeText = vi.fn(async () => {});

    expect(copyText(task, "A new title")).toBe("TASK-9 A new title");
    expect(await copyToClipboard("TASK-9 Redraw the view", { writeText })).toBe(true);
    expect(writeText).toHaveBeenCalledWith("TASK-9 Redraw the view");
    expect(await copyToClipboard("x", { writeText: async () => { throw new Error("refused"); } })).toBe(false);
    expect(await copyToClipboard("x", undefined)).toBe(false);
  });

  it("closes on a click outside the dialog or Escape, but not while editing", () => {
    const scrim = {}, dialog = {};

    expect(onScrim(scrim, scrim)).toBe(true);
    expect(onScrim(dialog, scrim)).toBe(false);
    expect(closesOnKey("Escape", false)).toBe(true);
    expect(closesOnKey("Escape", true)).toBe(false);
    expect(closesOnKey("Enter", false)).toBe(false);
  });
});

describe("the task view's body", () => {
  it("draws two columns: the read view on the left, the fields and live state in the rail", () => {
    const html = draw();
    const left = html.slice(html.indexOf('class="tvcol tvleft"'), html.indexOf('class="tvcol tvrail"'));
    const rail = html.slice(html.indexOf('class="tvcol tvrail"'));

    for (const text of ["Description", "Acceptance criteria", "1/2", "Definition of done", "0/1", "Implementation plan", "1. Write the test", "Notes", "Checked against the live config"]) expect(left, text).toContain(text);
    for (const text of ["Pull requests", "Machines", "priority"]) expect(rail, text).toContain(text);
    expect(left).not.toContain("Pull requests");
  });

  it("draws the description as Markdown paragraphs, headings and code", () => {
    const html = draw({ record: { ...record, description: "First para\n\n## Background\n\nSecond para\n\n```yaml\nstart_criteria: []\n```" } });

    expect(html).toContain("<p>First para</p>");
    expect(html).toContain("<h4>Background</h4>");
    expect(html).toContain("<p>Second para</p>");
    expect(html).toContain("<pre>start_criteria: []</pre>");
  });

  it("sizes the dialog and scrolls each column on its own, stacking rail-first below 1100px", () => {
    expect(styles).toMatch(/#kbm \.modal\.tv \{[^}]*width: clamp\(860px, 65vw, 1500px\)[^}]*height: min\(84vh, 980px\)/);
    expect(styles).toMatch(/#kbm \.tvbody \{[^}]*grid-template-columns: minmax\(0, 1fr\) clamp\(320px, 31%, 440px\)/);
    // each column scrolls through the page's one scrolling rule (scroll.test.ts); below 1100px the body scrolls instead
    expect(styles).toMatch(/#kbm \.tvcol,[^{}]*\{[^}]*overflow-y: auto/);
    expect(styles).toMatch(/@media \(max-width: 1100px\) \{[^@]*#kbm \.tvbody \.tvcol \{[^}]*overflow: visible/);
    expect(styles).toMatch(/@media \(max-width: 1100px\) \{[^@]*#kbm \.tvbody \{[^}]*flex-direction: column;/);
    expect(styles).toMatch(/@media \(max-width: 1100px\) \{[^@]*#kbm \.tvrail \{[^}]*order: -1/);
    expect(styles).not.toMatch(/column-reverse/);
  });
});

describe("the task view's right rail", () => {
  const holder = (n: number) => card(`TASK-${100 + n}`, n % 2 ? "waiting" : "ready", { dependencies: ["TASK-9"] });
  const many = [...board, ...Array.from({ length: 8 }, (_, i) => holder(i + 1))];
  const trail = Array.from({ length: 7 }, (_, i) => ({ state: `step_${i}`, event: `event_${i}`, at: 800 + i }));
  const rows = (html: string, section: string) => railOf(html).split('<section').find((x) => x.includes(`<span class="t">${section}</span>`)) ?? "";

  it("draws Status, Pull requests, CI history, Dependencies, Machines and Details in that order, each heading with its count", () => {
    const html = draw({ tasks: many });

    expect(headings(html)).toEqual(["Status", "Session", "Pull requests", "CI history", "Dependencies", "Machines", "Details"]);
    expect(rows(html, "Pull requests")).toContain('<span class="n">1</span>');
    expect(rows(html, "Dependencies")).toContain('<span class="n">9</span>');
    expect(rows(html, "Machines")).toContain('<span class="n">1</span>');
    expect(rows(html, "Status")).not.toContain('class="n"');
    expect(styles).toMatch(/#kbm \.tvrail \.sec \+ \.sec \{[^}]*border-top: 1px solid/);
    expect(styles).toMatch(/#kbm \.tvrail \.props td:first-child \{[^}]*width: calc\(74px \* var\(--fs\)\)/);
    expect(styles).toMatch(/#kbm \.tv \.sh \{[^}]*text-transform: uppercase/);
  });

  it("draws the lane and the time in it under Status, and leaves the time out when the board gave none", () => {
    expect(rows(draw(), "Status")).toMatch(/class="tvlane sm" data-lane="ready"><i><\/i>Ready<\/span><span class="k">for 5m<\/span>/);
    expect(rows(draw({ task: { ...task, entered: 0 } }), "Status")).not.toContain("for ");
  });

  describe("Session", () => {
    const link = "https://claude.ai/code/session_abc";
    const working = { ...task, lane: "in_progress", machines: [{ machine: "in-progress", state: "pr_opened", at: 900, model: "opus", steps: 7, trail: [] }] };
    const session = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => rows(draw({ record: { ...record, session: link }, ...over }), "Session");

    it("links the claiming session in a new tab, with the in-progress machine's model, state, age and steps under it", () => {
      const html = session({ task: working, lane: "In progress" });

      expect(html).toContain(`<a href="${link}" target="_blank" rel="noopener" class="big"><span class="p"></span>Open the claiming session ↗</a>`);
      expect(html).toContain('<div class="k">opus · pr opened · 2m ago · 7 steps</div>');
      expect(html).not.toContain("No session");
    });

    it("links the session alone when no machine is working the task", () => {
      const html = session({ task: { ...working, machines: [] }, lane: "In progress" });

      expect(html).toContain("Open the claiming session ↗");
      expect(html).not.toContain('class="k"');
    });

    it("says no session holds the task, pointing a startable task to Start session and an In progress one to being worked by hand", () => {
      const none = (over: Partial<KanbanTask>, lane: string) => rows(draw({ record: { ...record, session: "" }, ...lanes(lane, over) }), "Session");

      expect(none({}, "ready")).toContain("No session holds this task. ▶ Start session, top right, opens one.");
      expect(none({}, "review")).toContain("No session holds this task</");
      expect(none({}, "in_progress")).toContain("No session has claimed it: worked by hand");
      expect(none({}, "ready")).not.toContain("Open the claiming session");
    });

    it("ignores the link a startable task keeps from a session that no longer holds it, and a record that is not read yet", () => {
      expect(session({ ...lanes("ready") })).toContain("No session holds this task. ▶ Start session");
      expect(rows(draw({ record: null, task: working }), "Session")).toContain("worked by hand");
    });
  });

  it("draws each pull request as a link with its checks, or merged, and its open review threads", () => {
    const prs = [{ ...task.prs[0], threads: 2 }, { ...task.prs[0], number: 13, url: "http://pr/13", merged: true, checks: "pass" as const }];
    const html = rows(draw({ task: { ...task, prs } }), "Pull requests");

    expect(html).toContain('<a href="http://pr/12" target="_blank" rel="noopener">#12 ↗</a>');
    expect(html).toContain("checks pass");
    expect(html).toContain("2 open threads");
    expect(html).toMatch(/<a href="http:\/\/pr\/13"[^>]*>#13 ↗<\/a><span class="chk merged"><i><\/i>merged<\/span>/);
    expect(html).toContain("no open threads");
    expect(rows(draw({ task: { ...task, prs: [] } }), "Pull requests")).toContain("None yet");
  });

  it("draws how far an open pull request is behind main, and nothing when it is level or has no head branch", () => {
    const prs = [{ ...task.prs[0], behind_main: 4 }, { ...task.prs[0], number: 13, url: "http://pr/13", behind_main: 1 }, { ...task.prs[0], number: 14, url: "http://pr/14", behind_main: 0 }, { ...task.prs[0], number: 15, url: "http://pr/15" }];
    const html = rows(draw({ task: { ...task, prs } }), "Pull requests");

    expect(html).toContain("4 commits behind main");
    expect(html).toContain("1 commit behind main");
    expect(html.match(/behind main/g)).toHaveLength(2);
  });

  it("lists what the task depends on and what it holds, each row its id, title and lane", () => {
    const html = rows(draw({ tasks: many }), "Dependencies");

    expect(html.indexOf("Depends on")).toBeLessThan(html.indexOf("Holds"));
    expect(html).toMatch(/<button class="dep"><span class="id">TASK-1<\/span><span class="tt">title TASK-1<\/span><span class="tvlane sm" data-lane="done"><i><\/i>Done<\/span><\/button>/);
    expect(html).toContain("TASK-101");
    expect(rows(draw({ task: { ...task, dependencies: ["TASK-404"] } }), "Dependencies")).toContain("not on the board");
  });

  it("caps Holds at six rows and counts the rest", () => {
    const html = rows(draw({ tasks: many }), "Dependencies");

    expect(html.match(/<button class="dep">/g)).toHaveLength(7);
    for (const n of [101, 106]) expect(html).toContain(`TASK-${n}`);
    for (const n of [107, 108]) expect(html).not.toContain(`TASK-${n}`);
    expect(html).toContain("+2 more");
    expect(rows(draw({ tasks: many.slice(0, 5) }), "Dependencies")).not.toContain("more");
  });

  it("opens that task's modal when a dependency row is clicked", () => {
    const open = vi.fn();
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    act(() => root.render(<TaskView {...props({ tasks: many, open })} />));

    const buttons = [...host.querySelectorAll<HTMLButtonElement>(".tvrail button.dep")];
    act(() => buttons.find((b) => b.textContent?.includes("TASK-1") && !b.textContent.includes("TASK-10"))!.click());
    act(() => buttons.find((b) => b.textContent?.includes("TASK-103"))!.click());
    act(() => root.unmount());
    host.remove();

    expect(open.mock.calls).toEqual([["TASK-1"], ["TASK-103"]]);
  });

  it("draws each machine the task is in, collapsed to its last five transitions", () => {
    const machines = [{ machine: "in-progress", state: "pr_opened", at: 900, trail }, { machine: "ci", state: "running", at: 950, source: "GitHub", trail: [] }];
    const html = rows(draw({ task: { ...task, machines } }), "Machines");

    expect(html.match(/<details class="m">/g)).toHaveLength(2);
    expect(html).not.toMatch(/<details[^>]*open/);
    expect(html).toContain("<b>in-progress</b>");
    expect(html).toContain("pr opened");
    expect(html).toContain("<b>ci</b>");
    expect(html.match(/<li>/g)).toHaveLength(5);
    expect(html).toContain("event_6");
    expect(html).toContain("event_2");
    expect(html).not.toContain("event_1<");
    expect(rows(draw({ task: { ...task, machines: [] } }), "Machines")).toContain("In no machine right now");
  });

  it("draws the details as a read table, with needs-human highlighted and when the task was created", () => {
    const html = rows(draw({ task: { ...task, created: 400 } }), "Details");

    for (const text of ["profile", "@agent-standard-high", "priority", "High", "labels", "milestone", "m-89", "created", "10m ago"]) expect(html, text).toContain(text);
    expect(html).toContain('<span class="chip nh">needs-human</span>');
    expect(rows(draw({ task: { ...task, created: null } }), "Details")).toMatch(/created<\/td><td><span class="k">—<\/span>/);
  });

  it("edits only profile, priority and milestone in Details, and leaves Dependencies read-only", () => {
    const html = draw({ initialEditing: "details", tasks: many });

    expect(rows(html, "Details")).toMatch(/data-field="profile"[\s\S]*data-field="priority"[\s\S]*data-field="milestone"/);
    expect(rows(html, "Details")).not.toContain('data-field="labels"');
    expect(rows(html, "Dependencies")).not.toContain("data-field");
    expect(rows(html, "Dependencies")).toContain('<span class="id">TASK-1</span>');
  });
});

const at = (sec: number) => new Date(sec * 1000).toISOString();
const criterion = (over: Partial<StartCriterion>): StartCriterion => ({
  id: "rows", kind: "sql", expr: "select count(*) from runs", cmp: "equals", want: 3, status: "unmet", observed: 2, error: null, checked: at(700), ...over,
});
const criteria: StartCriterion[] = [
  criterion({ id: "soak-24h", kind: "prom", expr: "time()", cmp: "at_least", want: 1791400000, status: "unmet", observed: 1791336841 }),
  criterion({ id: "rows", status: "met", observed: 3 }),
  criterion({ id: "pin-moved", kind: "file_changed_since", expr: "starpulse", cmp: "since", want: "2026-10-05", status: "unmet", observed: 0 }),
  criterion({ id: "queue", kind: "prom", expr: "up", cmp: "at_least", want: 1, status: "not evaluated", observed: null, checked: null }),
  criterion({ id: "gate", kind: "sql", expr: "select 1", status: "error", observed: null, error: "criteria: exit 2: prometheus is down", checked: null }),
];
const sectionOf = (html: string, name: string) => {
  const rail = railOf(html);
  const from = rail.indexOf(`>${name}</span>`);
  return from < 0 ? "" : rail.slice(from, rail.indexOf("</section>", from));
};
const withCriteria = (list: StartCriterion[] | undefined) => draw({ record: { ...record, start_criteria: list } });

describe("the Start Criteria section", () => {
  it("draws each criterion's mark, kind, id, threshold and last value, with how long ago it was checked", () => {
    const html = sectionOf(withCriteria(criteria), "Start Criteria");

    expect(html).toContain("1/5 met");
    expect(html).toContain("○ unmet");
    expect(html).toContain("✓ met");
    for (const text of ["soak-24h", "prom", "rows", "sql", "select count(*) from runs", "equals 3 · last 3 · checked 5m ago", "since 2026-10-05 · last 0 · checked 5m ago"]) expect(html, text).toContain(text);
  });

  it("reads a time() criterion as when it opens, in Arizona time", () => {
    const html = sectionOf(withCriteria(criteria), "Start Criteria");

    expect(html).toContain("opens Oct 7, 12:06 MST · checked 5m ago");
    expect(html).not.toContain("at least 1791400000");
  });

  it("draws a criterion that was not evaluated with no mark and a muted note", () => {
    const card = sectionOf(withCriteria([criteria[3]]), "Start Criteria");

    expect(card).toContain("not evaluated");
    expect(card).not.toMatch(/[✓○]/);
    expect(card).toContain('class="c pending"');
    expect(card).toContain("at least 1");
  });

  it("draws an evaluator error as its message, with no mark", () => {
    const card = sectionOf(withCriteria([criteria[4]]), "Start Criteria");

    expect(card).toContain('class="c error"');
    expect(card).toContain("criteria: exit 2: prometheus is down");
    expect(card).not.toMatch(/[✓○]/);
    expect(card).not.toContain("last ");
  });

  it("sits in the right rail after Status and Session and is absent when the task has no criteria", () => {
    expect(headings(withCriteria(criteria)).slice(0, 3)).toEqual(["Status", "Session", "Start Criteria"]);
    expect(headings(withCriteria([]))).not.toContain("Start Criteria");
    expect(headings(withCriteria(undefined))).not.toContain("Start Criteria");
    expect(html(withCriteria(criteria)).left).not.toContain("Start Criteria</span>");
  });
});

const html = (markup: string) => ({ left: markup.slice(markup.indexOf('class="tvcol tvleft"'), markup.indexOf('class="tvcol tvrail"')) });
const yaml = "```yaml\nstart_criteria:\n- id: rows\n  kind: sql\n```";

describe("the description's start_criteria block", () => {
  it("gives way to a pointer to the section when the record carries the criteria", () => {
    const { left } = html(draw({ record: { ...record, description: `Wait.\n\n## Start Criteria\n\n${yaml}`, start_criteria: criteria } }));

    expect(left).toContain("<h4>Start Criteria</h4>");
    expect(left).toContain("Start Criteria are drawn in the side panel, each with its result");
    expect(left).not.toContain("start_criteria:");
  });

  it("keeps the raw block when there are no criteria to draw in its place", () => {
    const { left } = html(draw({ record: { ...record, description: `Wait.\n\n${yaml}` } }));

    expect(left).toContain("<pre>start_criteria:\n- id: rows\n  kind: sql</pre>");
  });
});

describe("the task view's CI history", () => {
  const step = (event: string, state: string, at: number) => ({ event, state, at });
  const pull = (number: number) => ({ number, url: `http://pr/${number}`, checks: "pass" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false });
  const trail = [
    step("PR_OPENED", "opened", 1), step("PUSHED", "running", 2), step("CHECKS_FAILED", "failing", 3), step("RERUN", "running", 4), step("CHECKS_PASSED", "passing", 5),
    step("CONFLICTED", "conflicting", 6), step("REBASED", "running", 7), step("CHECKS_PASSED", "passing", 8), step("MERGED", "merged", 9),
    step("PR_OPENED", "opened", 10), step("PUSHED", "running", 11), step("CHECKS_FAILED", "failing", 12),
  ];
  const ci = (source: string | null = "GitHub") => [{ machine: "ci", state: "failing", at: 12, source, trail }];
  const section = (html: string) => railOf(html).split('<section class="sec rs">').find((s) => s.includes(">CI history<")) ?? "";
  const two = { prs: [pull(15), pull(12)], machines: ci() };

  it("totals the task's runs, re-runs, rebases and conflicts, then gives each pull request its own counts and state", () => {
    const html = section(draw({ task: { ...task, ...two } }));

    expect(html).toContain('<span class="n">2</span>');
    expect(html).toMatch(/2 runs/);
    expect(html).toMatch(/1 re-run/);
    expect(html).toMatch(/1 rebase/);
    expect(html).toMatch(/1 conflict/);
    expect(html.indexOf("#12")).toBeGreaterThan(-1);
    expect(html.indexOf("#12")).toBeLessThan(html.indexOf("#15"));
    expect(html).toMatch(/#12[\s\S]*merged[\s\S]*#15[\s\S]*failing/);
  });

  it("totals only when there are two pull requests to total, since one pull request's counts are the task's", () => {
    const one = { prs: [pull(12)], machines: [{ ...ci()[0], trail: trail.slice(0, 9) }] };

    expect(section(draw({ task: { ...task, ...two } }))).toContain('class="tot"');
    expect(section(draw({ task: { ...task, ...one } }))).not.toContain('class="tot"');
    expect(section(draw({ task: { ...task, ...one } }))).toMatch(/#12[\s\S]*merged/);
  });

  it("draws the state in the mapped colour only when a third party moves the machine", () => {
    expect(section(draw({ task: { ...task, ...two } }))).toContain("mapped");
    expect(section(draw({ task: { ...task, prs: two.prs, machines: ci(null) } }))).not.toContain("mapped");
    expect(styles).toMatch(/#kbm \.tvrail \.ci \.st\.mapped[^{]*\{[^}]*var\(--mapped\)/);
  });

  it("says why it is empty: no pull request, or none recorded yet", () => {
    expect(section(draw({ task: { ...task, prs: [], machines: [] } }))).toContain("No pull request yet");
    expect(section(draw({ task: { ...task, machines: [] } }))).toContain("No CI recorded yet");
  });
});

describe("opening the task view stays off the layout engine", () => {
  it("sizes its textareas in CSS, so a mount reads no scrollHeight and sets no height", () => {
    const read = vi.spyOn(HTMLTextAreaElement.prototype, "scrollHeight", "get").mockReturnValue(0);
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    act(() => root.render(<TaskView {...props()} />));
    const title = host.querySelector<HTMLTextAreaElement>('textarea[data-field="title"]')!;

    expect(read).not.toHaveBeenCalled();
    expect(title.style.height).toBe("");
    expect(styles).toMatch(/#kbm \.tv textarea\.fv:not\(\.long\)\s*\{[^}]*field-sizing:\s*content/);
    act(() => root.unmount());
    host.remove();
    read.mockRestore();
  });

  it("dims the board with a flat scrim: a backdrop blur makes every frame under it repaint the whole board", () => {
    const scrim = styles.match(/^#kbm \{[^}]*\}/m)![0];

    expect(scrim).toContain("background:");
    expect(scrim).not.toContain("backdrop-filter");
  });
});

describe("the Move to menu under a moving pointer", () => {
  it("commits nothing while the pointer moves within the row already lit, and lights the row it moves onto", () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.body.appendChild(document.createElement("div")), root = createRoot(host);
    let commits = 0;
    act(() => root.render(<Profiler id="tv" onRender={() => commits++}><TaskView {...props()} /></Profiler>));
    try {
      act(() => host.querySelector<HTMLButtonElement>('.mv button[aria-haspopup="menu"]')!.click());
      const rows = [...host.querySelectorAll<HTMLElement>('.mvmenu [role="menuitem"]')];
      const move = (row: HTMLElement) => act(() => void row.dispatchEvent(new MouseEvent("mousemove", { bubbles: true })));
      move(rows[0]);
      const before = commits;
      for (let i = 0; i < 5; i++) move(rows[0]);
      expect(commits).toBe(before);
      move(rows[1]);
      expect(rows[1].classList.contains("on")).toBe(true);
    } finally {
      act(() => root.unmount());
      host.remove();
    }
  });
});
