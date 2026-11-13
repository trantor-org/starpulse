import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WarnConfirm, type WarnConfirmProps } from "./WarnConfirm";
import type { KanbanTask } from "./kanbanModel";

const task: KanbanTask = {
  id: "TASK-9", title: "Redraw the view", lane: "in_progress", milestone: "m-89", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [],
  description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
};
const ONE = [{ reason: "Review needs every Acceptance Criterion checked: verify each gate", skill: "" }];
const TWO = [{ reason: "Review needs a ready pull request: run `starpulse command run ready`", skill: "deliver" }, ...ONE];
const draw = (over: Partial<WarnConfirmProps> = {}) => renderToStaticMarkup(
  <WarnConfirm task={task} from="In Progress" to="Review" warnings={TWO} busy={false} refused={null} cancel={() => {}} confirm={() => {}} {...over} />,
);

describe("the warn-and-confirm box", () => {
  it("names the move and lists every broken rule with Cancel and Confirm", () => {
    const html = draw();

    expect(html).toContain('role="alertdialog"');
    expect(html).toContain("Move TASK-9 to Review?");
    expect(html).toContain("Redraw the view · In Progress → Review");
    expect(html).toContain("This move breaks 2 rules of the Review lane. An agent making it would be refused.");
    expect(html.match(/class="warn"/g)).toHaveLength(2);
    expect(html).toContain("<code>starpulse command run ready</code>");
    expect(html).toContain("Satisfied by");
    expect(html).toContain("deliver");
    expect(html).toContain("Cancel");
    expect(html).toContain('class="danger"');
    expect(html).toContain(">Confirm<");
    expect(html).not.toContain("disabled");
    expect(html).not.toContain('role="alert"');
  });

  it("says rule in the singular and names no skill the rule does not", () => {
    const html = draw({ warnings: ONE });

    expect(html).toContain("This move breaks 1 rule of the Review lane.");
    expect(html).not.toContain("Satisfied by");
  });

  it("disables both buttons and reads Moving… while the write runs", () => {
    const html = draw({ busy: true });

    expect(html).toContain("Moving…");
    expect(html.match(/disabled=""/g)).toHaveLength(2);
  });

  it("shows the refusal with Confirm disabled and Cancel live", () => {
    const html = draw({ refused: "TASK-9 changed since the board was read." });

    expect(html).toContain('role="alert"');
    expect(html).toContain("Not moved: TASK-9 changed since the board was read.");
    expect(html.match(/disabled=""/g)).toHaveLength(1);
  });
});
