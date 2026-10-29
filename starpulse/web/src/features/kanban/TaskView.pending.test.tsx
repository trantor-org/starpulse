// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TaskView } from "./TaskView";
import { props, task } from "../../tests/taskViewFixtures";

const draw = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => renderToStaticMarkup(<TaskView {...props(over)} />);
const skeletons = (html: string) => [...html.matchAll(/<section class="sec skel" aria-label="([^"]+)"/g)].map((m) => m[1]);
const carried = {
  ...task,
  acceptanceCriteria: [{ n: 1, text: "A snapshot criterion", checked: true }],
  definitionOfDone: [{ n: 1, text: "A snapshot DoD item", checked: false }],
};

describe("the task view while its record is read", () => {
  it("draws the AC and DoD the snapshot entry carries before the record arrives", () => {
    const html = draw({ record: undefined, task: carried });

    expect(html).toContain("A snapshot criterion");
    expect(html).toContain("A snapshot DoD item");
    expect(html).toContain("1/1");
    expect(skeletons(html)).toEqual(["Implementation plan", "Notes"]);
  });

  it("draws a skeleton in AC, DoD, plan and notes while the record read is pending, never a dash", () => {
    const html = draw({ record: undefined });

    expect(skeletons(html)).toEqual(["Acceptance criteria", "Definition of done", "Implementation plan", "Notes"]);
    expect(html).toContain('aria-busy="true"');
  });

  it("drops the skeleton once the record arrives or the read fails", () => {
    expect(skeletons(draw())).toEqual([]);
    expect(skeletons(draw({ record: undefined, readNote: "The record could not be read" }))).toEqual([]);
  });
});
