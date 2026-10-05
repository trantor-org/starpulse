import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { KanbanTask } from "./kanban";
import { TaskView } from "./TaskView";
import type { TaskRecord } from "./taskView";

const task: KanbanTask = {
  id: "TASK-9", title: "Redraw the view", lane: "ready", milestone: "m-89", labels: ["needs-human"], assignee: "@agent-standard-high",
  dependencies: ["TASK-1"], openDeps: 0, prs: [{ number: 12, url: "http://pr/12", checks: "pass", merged: false, threads: 0, stale: false }],
  description: "from the snapshot", live: null, released: false,
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

describe("the task view in read mode", () => {
  it("draws the plan, notes and checks the record carries", () => {
    const html = draw();

    expect(html).toContain("1. Write the test");
    expect(html).toContain("Checked against the live config");
    expect(html).toContain("A Vitest test failed first");
    expect(html).toContain("The completing-tasks skill was invoked");
    expect(html).toContain("1/2");
  });

  it("frames every editable field with the faint frame, locked against input", () => {
    const html = draw();
    const framed = html.match(/class="fv[ "][^>]*>/g) ?? [];

    // title, profile, priority, labels, milestone, dependencies, description, two checklists' items, plan and notes
    expect(framed.length).toBeGreaterThanOrEqual(12);
    expect(html).toMatch(/<textarea[^>]*class="fv[^"]*long[^>]*readOnly=""|<textarea[^>]*readOnly=""[^>]*class="fv[^"]*long/);
    expect(html).toMatch(/<input[^>]*type="checkbox"[^>]*disabled=""/);
  });

  it("keeps the scrolling plan and notes boxes reachable by keyboard so they can be scrolled", () => {
    const boxes = draw().match(/<textarea[^>]*class="fv long"[^>]*>/g) ?? [];

    expect(boxes).toHaveLength(2);
    for (const box of boxes) expect(box).not.toContain('tabindex="-1"');
  });

  it("draws Edit and Archive only when the board can", () => {
    expect(draw()).toContain("Archive…");
    expect(draw()).toContain("Edit");
    const readOnly = draw({ capabilities: { edit: false, archive: false } });
    expect(readOnly).not.toContain("Archive…");
    expect(readOnly).not.toContain("Edit");
    expect(draw({ capabilities: undefined })).not.toContain("Archive…");
  });

  it("puts Start session beside the Move to menu in the footer", () => {
    const html = draw();
    const foot = html.slice(html.indexOf('class="tvfoot"'));

    expect(foot).toContain("Move to");
    expect(foot).toContain("▶ Start session");
    expect(foot.indexOf("Move to")).toBeLessThan(foot.indexOf("▶ Start session"));
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
