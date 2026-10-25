// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TaskView } from "./TaskView";
import { props, record } from "../../tests/taskViewFixtures";

const draw = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => renderToStaticMarkup(<TaskView {...props(over)} />);
const leftOf = (html: string) => html.slice(0, html.indexOf('class="tvcol tvrail"'));

describe("task dialog body", () => {
  it("draws a GFM table, a fenced block and a TASK-N link that opens that task", () => {
    const description = "| Field | Size |\n| --- | ---: |\n| Lane | 2 |\n\n```yaml\na: 1\n```\n\nSee TASK-1 for the rest.";
    const html = draw({ record: { ...record, description } });

    expect(html).toContain("<table>");
    expect(html).toContain('<th class="r">Size</th>');
    expect(html).toContain("<td>Lane</td>");
    expect(html).toContain("<pre>a: 1</pre>");
    expect(html).toContain('<a class="tl" href="?view=kanban&amp;task=TASK-1">TASK-1</a>');
  });

  it("drops the creation signals: Duplicate Search, Duplicate Resolution and ADR Needed", () => {
    const description = "Intro.\n\n## Duplicate Search\n\nnone found\n\n## Background\n\nKept text.\n\n## ADR Needed\n\nNo\n\n## Duplicate Resolution\n\ndupes resolved\n\n```md\n## ADR Needed\n```";
    const html = draw({ record: { ...record, description } });

    for (const gone of ["Duplicate Search", "none found", "ADR Needed", "Duplicate Resolution", "dupes resolved"]) expect(html, gone).not.toContain(gone);
    expect(html).toContain("<h4>Background</h4>");
    expect(html).toContain("Kept text.");
  });

  it("body sections: hides an empty plan, draws Definition of done and drops the Assignee line from Notes", () => {
    const blank = draw({ record: { ...record, plan: " \n " } });
    expect(blank).not.toContain("Implementation plan");

    const html = draw({ record: { ...record, notes: "**Assignee:** bfd2745a-fede-456b-ab79-895a15a03de2\nChecked against the live config" } });
    const left = leftOf(html);
    expect(left).toContain("Definition of done");
    expect(left).toContain("The completing-tasks skill was invoked");
    expect(left).toContain("Checked against the live config");
    expect(left).not.toContain("bfd2745a-fede-456b-ab79-895a15a03de2");
  });
});
