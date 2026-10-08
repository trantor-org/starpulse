import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { NewTaskAction, NewTaskForm, type NewTaskFormProps } from "./NewTask";
import { EMPTY_DRAFT } from "./newTask";

const draw = (over: Partial<NewTaskFormProps> = {}) => renderToStaticMarkup(
  <NewTaskForm draft={EMPTY_DRAFT} busy={false} refused={null} lane="To Do" assignees={["@agent-fast-low"]} milestones={["m-1"]}
    change={() => {}} cancel={() => {}} submit={() => {}} {...over} />,
);

describe("the New task form", () => {
  it("is a dialog like the task view, with every field a new task takes, landing in the starting lane", () => {
    const html = draw();

    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-label="New task"');
    for (const field of ["Title", "Assignee", "Priority", "Labels", "Milestone", "Dependencies", "Description", "Acceptance criterion #1"]) {
      expect(html).toContain(`aria-label="${field}"`);
    }
    expect(html).toContain("Lands in To Do");
    expect(html).toContain("+ Add criterion");
    expect(html).not.toContain('role="alert"');
  });

  it("suggests the board's assignees and milestones", () => {
    const html = draw();

    expect(html).toContain('<option value="@agent-fast-low">');
    expect(html).toContain('<option value="m-1">');
  });

  it("keeps the whole draft and shows the board's reason after a refusal", () => {
    const draft = { ...EMPTY_DRAFT, title: "Write the docs", description: "Every lane", labels: "docs, ui", acceptanceCriteria: ["Names every lane"] };
    const html = draw({ draft, refused: "the board is read-only" });

    expect(html).toContain("Write the docs");
    expect(html).toContain("Every lane");
    expect(html).toContain('value="docs, ui"');
    expect(html).toContain('value="Names every lane"');
    expect(html).toContain('role="alert"');
    expect(html).toContain("the board is read-only");
  });

  it("will not create without a title, nor anything while a create runs", () => {
    expect(draw({ draft: { ...EMPTY_DRAFT, title: "  " } })).toMatch(/<button[^>]*disabled=""[^>]*>Create/);
    expect(draw({ draft: { ...EMPTY_DRAFT, title: "x" }, busy: true })).toMatch(/<button[^>]*disabled=""[^>]*>Creating/);
    expect(draw({ draft: { ...EMPTY_DRAFT, title: "x" } })).not.toMatch(/<button[^>]*disabled=""[^>]*>Create/);
  });
});

describe("the New task action beside the task count", () => {
  const action = (capabilities?: { edit: boolean; archive: boolean; create?: boolean }) =>
    renderToStaticMarkup(<NewTaskAction capabilities={capabilities} lane="To Do" assignees={[]} milestones={[]} created={() => {}} />);

  it("is a button, drawn when the snapshot says the board can create", () => {
    const html = action({ edit: true, archive: true, create: true });

    expect(html).toContain("+ New task");
    expect(html).not.toContain('role="dialog"');
  });

  it("is absent when the board cannot create, or the snapshot says nothing", () => {
    expect(action({ edit: true, archive: true, create: false })).toBe("");
    expect(action({ edit: true, archive: true })).toBe("");
    expect(action()).toBe("");
  });
});
