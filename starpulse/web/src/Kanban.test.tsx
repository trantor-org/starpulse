import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Card } from "./Kanban";
import type { KanbanTask } from "./kanban";

const task: KanbanTask = {
  id: "PROJ-1", title: "A title long enough to need two lines in a comfortable card", lane: "in_progress", milestone: "m-1", labels: ["feature", "needs-human"], assignee: "@agent-standard-high",
  dependencies: [], openDeps: 2, prs: [], description: "", live: { machine: "in-progress", state: "red_proven", at: 100 }, released: false, moves: {},
};
const draw = (compact: boolean) => renderToStaticMarkup(<Card task={task} now={160} marks={{}} names={{}} onOpen={() => {}} dismiss={() => {}} compact={compact} />);

describe("a Kanban card's density", () => {
  it("keeps the footer of labels, dependencies and profile when comfortable", () => {
    const html = draw(false);

    expect(html).toContain('class="foot"');
    expect(html).toContain("needs-human");
    expect(html).toContain("standard-high");
    expect(html).not.toContain("compact");
  });

  it("drops the footer but keeps the id, title and machine line when compact", () => {
    const html = draw(true);

    expect(html).toContain('class="card compact"');
    expect(html).not.toContain('class="foot"');
    expect(html).not.toContain("needs-human");
    expect(html).toContain("PROJ-1");
    expect(html).toContain("A title long enough");
    expect(html).toContain("red proven");
    expect(html).toContain("1m");
  });
});
