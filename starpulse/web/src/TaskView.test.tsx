// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanban";
import { TaskView } from "./TaskView";
import { closesOnKey, copyText, copyToClipboard, menuKey, onScrim, type TaskRecord } from "./taskView";

const styles = readFileSync(new URL("./style.css", import.meta.url), "utf8");

const task: KanbanTask = {
  id: "TASK-9", title: "Redraw the view", lane: "ready", milestone: "m-89", labels: ["needs-human"], assignee: "@agent-standard-high",
  dependencies: ["TASK-1"], openDeps: 0, prs: [{ number: 12, url: "http://pr/12", checks: "pass", merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false }],
  description: "from the snapshot", live: null, released: false, entered: 0,
  moves: { in_progress: { allowed: true, reason: "", skill: "" }, review: { allowed: false, reason: "no review yet", skill: "completing-tasks" } },
};
const record: TaskRecord = {
  title: "Redraw the view", profile: "@agent-standard-high", priority: "High", labels: ["needs-human"], milestone: "m-89", dependencies: ["TASK-1"],
  description: "the full description", plan: "1. Write the test\n2. Make it pass", notes: "Checked against the live config",
  acceptanceCriteria: [{ n: 1, text: "A Vitest test failed first", checked: true }, { n: 2, text: "make lint-changed passes", checked: false }],
  definitionOfDone: [{ n: 1, text: "The completing-tasks skill was invoked", checked: false }],
};
const draw = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => renderToStaticMarkup(
  <TaskView task={task} record={record} lane="Ready" machine="—" profiles={[]} milestones={[]} refusal={null} startNote={null}
    capabilities={{ edit: true, archive: true }} saving={false} claiming={false} close={() => {}} hide={() => {}} constellation={() => {}}
    move={() => {}} start={() => {}} {...over} />,
);

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

  it("frames the title, the details and the checks, locked against input, and draws the long text unframed", () => {
    const html = draw();
    const framed = html.match(/class="fv[ "][^>]*>/g) ?? [];

    // title, profile, priority, labels, milestone, dependencies
    expect(framed.length).toBeGreaterThanOrEqual(6);
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
    const html = draw({ record: { ...record, priority: "high" } });

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

  it("keeps every field in the same framed element in read and edit modes", () => {
    const read = draw();
    const edit = draw({ initialEditing: true });

    // the long text and the checks are plain read rows that become these framed boxes only in edit mode
    expect(frames(edit).filter(([field]) => !["description", "plan", "notes", "acceptanceCriteria", "definitionOfDone"].includes(field))).toEqual(frames(read));
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
    for (const text of ["pull requests", "machine", "priority"]) expect(rail, text).toContain(text);
    expect(left).not.toContain("pull requests");
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
    expect(styles).toMatch(/#kbm \.tvrail td \{[^}]*display: block/);
    expect(styles).toMatch(/@media \(max-width: 1100px\) \{[^@]*#kbm \.tvbody \{[^}]*flex-direction: column;/);
    expect(styles).toMatch(/@media \(max-width: 1100px\) \{[^@]*#kbm \.tvrail \{[^}]*order: -1/);
    expect(styles).not.toMatch(/column-reverse/);
  });
});
