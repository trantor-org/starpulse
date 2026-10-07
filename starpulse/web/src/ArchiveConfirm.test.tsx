import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ArchiveConfirm, type ArchiveConfirmProps } from "./ArchiveConfirm";
import { COLUMNS, type KanbanTask } from "./kanban";

const task = (lane: string, over: Partial<KanbanTask> = {}): KanbanTask => ({
  id: "TASK-9", title: "Redraw the view", lane, milestone: "m-89", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [],
  description: "", live: null, released: false, moves: {}, entered: 0, ...over,
});
const pull = { number: 12, url: "http://pr/12", checks: "pending" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false };
const draw = (t: KanbanTask, over: Partial<ArchiveConfirmProps> = {}) => renderToStaticMarkup(
  <ArchiveConfirm task={t} lane="Ready" reason="" busy={false} refused={null} onReason={() => {}} cancel={() => {}} confirm={() => {}} {...over} />,
);

describe("the archive confirm", () => {
  it("is offered from every lane, naming the task and its lane", () => {
    for (const lane of COLUMNS) {
      const html = draw(task(lane), { lane });

      expect(html).toContain('role="alertdialog"');
      expect(html).toContain("Archive TASK-9?");
      expect(html).toContain(`Redraw the view · ${lane}`);
      expect(html).toContain("Reason");
      expect(html).not.toContain("warn");
    }
  });

  it("warns first about an open pull request, linking it, and says archiving does not close it", () => {
    const html = draw(task("review", { prs: [pull] }));

    expect(html).toContain('class="warn"');
    expect(html).toContain('href="http://pr/12"');
    expect(html).toContain("#12");
    expect(html).toContain("is open (checks pending)");
    expect(html).toContain("does not close it");
  });

  it("warns first about a live agent session, naming its machine and state", () => {
    const html = draw(task("in_progress", { live: { machine: "in-progress", state: "implementing", at: 100 } }));

    expect(html).toContain('class="warn"');
    expect(html).toContain("agent session is working this task");
    expect(html).toContain("in-progress · implementing");
    expect(html).toContain("does not stop it");
  });

  it("shows both warnings for a task with a pull request and a session", () => {
    const html = draw(task("in_progress", { prs: [pull], live: { machine: "in-progress", state: "implementing", at: 100 } }));

    expect(html.match(/class="warn"/g)).toHaveLength(2);
  });

  it("shows a refusal's reason, keeps the task named and offers Try again", () => {
    const html = draw(task("ready"), { refused: "backlog task archive TASK-9 timed out after 30 s; the task was not archived." });

    expect(html).toContain('role="alert"');
    expect(html).toContain("Not archived: backlog task archive TASK-9 timed out after 30 s; the task was not archived.");
    expect(html).toContain("Try again");
  });

  it("carries the typed reason and locks the buttons while it archives", () => {
    const html = draw(task("ready"), { reason: "superseded", busy: true });

    expect(html).toContain("superseded");
    expect(html).toContain("Archiving…");
    expect(html.match(/<button[^>]*disabled=""/g)).toHaveLength(2);
  });
});
