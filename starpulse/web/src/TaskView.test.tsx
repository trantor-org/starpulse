// @vitest-environment jsdom
// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
// @ts-expect-error Same Node-only import: jsdom swaps the global URL for one readFileSync refuses.
import { URL as NodeURL } from "node:url";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanban";
import { TaskView } from "./TaskView";
import { closesOnKey, copyText, copyToClipboard, menuKey, onScrim, type TaskRecord } from "./taskView";

const styles = readFileSync(new NodeURL("./style.css", import.meta.url), "utf8");

const task: KanbanTask = {
  id: "TASK-9", title: "Redraw the view", lane: "ready", milestone: "m-89", labels: ["needs-human"], assignee: "@agent-standard-high",
  dependencies: ["TASK-1"], openDeps: 0, prs: [{ number: 12, url: "http://pr/12", checks: "pass", merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false }],
  description: "from the snapshot", live: null, released: false, entered: 700, created: 100, workableSince: null,
  machines: [{ machine: "in-progress", state: "pr_opened", at: 900, trail: [] }],
  moves: { in_progress: { allowed: true, reason: "", skill: "" }, review: { allowed: false, reason: "no review yet", skill: "completing-tasks" } },
};
const record: TaskRecord = {
  title: "Redraw the view", profile: "@agent-standard-high", priority: "High", labels: ["needs-human"], milestone: "m-89", dependencies: ["TASK-1"],
  description: "the full description", plan: "1. Write the test\n2. Make it pass", notes: "Checked against the live config",
  acceptanceCriteria: [{ n: 1, text: "A Vitest test failed first", checked: true }, { n: 2, text: "make lint-changed passes", checked: false }],
  definitionOfDone: [{ n: 1, text: "The completing-tasks skill was invoked", checked: false }],
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
    expect(html).toMatch(/<input[^>]*type="checkbox"[^>]*disabled=""/);
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
    const html = draw({ record: { ...record, priority: "high" }, initialEditing: true });

    expect(html).toContain('<option value="High" selected="">High</option>');
    expect(html).not.toContain('<option value="high"');
  });

  it("falls back to the snapshot's fields until the record arrives", () => {
    const html = draw({ record: null });

    expect(html).toContain("from the snapshot");
    expect(html).not.toContain("Implementation plan");
  });
});

describe("the task view in edit mode", () => {
  const frames = (html: string) => [...html.matchAll(/<(textarea|select|div|input)[^>]*data-field="([^"]+)"[^>]*class="([^"]*\bfv\b[^"]*)"[^>]*>/g)]
    .map((m) => [m[2], m[1], m[3].replace(/\b(dirty|bad)\b/g, "").replace(/\s+/g, " ").trim()]);

  it("keeps the title in the same framed element in read and edit modes and frames every other field only in edit mode", () => {
    const read = draw();
    const edit = draw({ initialEditing: true });

    // the details, dependencies, long text and checks are plain read rows that become framed boxes only in edit mode
    expect(frames(read).map(([field]) => field)).toEqual(["title"]);
    expect(frames(edit).filter(([field]) => field === "title")).toEqual(frames(read));
    expect(frames(edit).map(([field]) => field)).toEqual(expect.arrayContaining([
      "title", "profile", "priority", "labels", "milestone", "dependencies", "description", "acceptanceCriteria",
      "definitionOfDone", "plan", "notes",
    ]));
    expect(edit).toContain("0 fields changed");
    expect(edit).toContain("Save");
    expect(edit).toContain("Cancel");
    expect(edit).toContain('class="modal tv editing"');
    expect(read).not.toContain('class="remove"');
    expect(edit.match(/class="remove"/g)).toHaveLength(3);
    expect(styles).toMatch(/\.item \{[^}]*grid-template-columns: 22px 1fr 20px/);
  });

  it("disables Move and Start for the whole edit", () => {
    const html = draw({ initialEditing: true });
    const head = headOf(html);

    expect(head).toMatch(/class="mvbtn"[^>]*disabled=""/);
    expect(head).toMatch(/class="startbtn"[^>]*disabled=""/);
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

  it("draws Status, Pull requests, Dependencies, Machines and Details in that order, each heading with its count", () => {
    const html = draw({ tasks: many });

    expect(headings(html)).toEqual(["Status", "Pull requests", "Dependencies", "Machines", "Details"]);
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

  it("keeps the framed fields in edit mode, Dependencies included", () => {
    const html = draw({ initialEditing: true, tasks: many });

    expect(rows(html, "Details")).toMatch(/data-field="profile"[\s\S]*data-field="priority"[\s\S]*data-field="labels"[\s\S]*data-field="milestone"/);
    expect(rows(html, "Dependencies")).toContain('data-field="dependencies"');
    expect(rows(html, "Dependencies")).not.toContain('<span class="id">TASK-1</span>');
  });
});
