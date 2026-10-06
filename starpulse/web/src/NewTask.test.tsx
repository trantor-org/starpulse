import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { NewTask, NewTaskAction, type NewTaskProps } from "./NewTask";

const draw = (over: Partial<NewTaskProps> = {}) => renderToStaticMarkup(
  <NewTask open title="" busy={false} refused={null} onOpen={() => {}} onTitle={() => {}} cancel={() => {}} submit={() => {}} {...over} />,
);

describe("the New task action", () => {
  it("is a button until it is opened", () => {
    const html = draw({ open: false });

    expect(html).toContain("New task");
    expect(html).not.toContain("<input");
  });

  it("opens an inline title field with Add and Cancel", () => {
    const html = draw();

    expect(html).toContain("<input");
    expect(html).toContain('aria-label="New task title"');
    expect(html).toContain("Add");
    expect(html).toContain("Cancel");
    expect(html).not.toContain('role="alert"');
  });

  it("keeps the typed title and shows the board's reason after a refusal", () => {
    const html = draw({ title: "Write the docs", refused: "the board is read-only" });

    expect(html).toContain('value="Write the docs"');
    expect(html).toContain('role="alert"');
    expect(html).toContain("Not created: the board is read-only");
  });

  it("will not add an empty title, nor anything while a create runs", () => {
    expect(draw({ title: "  " })).toMatch(/<button[^>]*disabled=""[^>]*>Add/);
    expect(draw({ title: "x", busy: true })).toMatch(/<button[^>]*disabled=""[^>]*>Adding/);
    expect(draw({ title: "x" })).not.toMatch(/<button[^>]*disabled=""[^>]*>Add/);
  });
});

describe("the New task action beside the task count", () => {
  it("is drawn when the snapshot says the board can create", () => {
    expect(renderToStaticMarkup(<NewTaskAction capabilities={{ edit: true, archive: true, create: true }} created={() => {}} />)).toContain("New task");
  });

  it("is absent when the board cannot create, or the snapshot says nothing", () => {
    expect(renderToStaticMarkup(<NewTaskAction capabilities={{ edit: true, archive: true, create: false }} created={() => {}} />)).toBe("");
    expect(renderToStaticMarkup(<NewTaskAction capabilities={{ edit: true, archive: true }} created={() => {}} />)).toBe("");
    expect(renderToStaticMarkup(<NewTaskAction created={() => {}} />)).toBe("");
  });
});
