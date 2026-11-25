import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Card } from "./Kanban";
import type { KanbanTask } from "./kanbanModel";
import type { Pull } from "../../api/types.gen";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";

const base: KanbanTask = {
  id: "PROJ-1", title: "T", lane: "ready", milestone: "m-1", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "",
  live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
};
const draw = (over: Partial<KanbanTask> = {}, holds = 0, now = 1000, chain?: "self" | "holds" | "waits") =>
  renderToStaticMarkup(<Card task={{ ...base, ...over }} holds={holds} chain={chain} now={now} marks={{}} names={{}} roles={LIFECYCLE_ROLES} onOpen={() => {}} dismiss={() => {}} />);
const pull = (over: Partial<Pull> = {}): Pull => ({ number: 7, repo: "o/r", url: "http://pr/7", checks: "pass", merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false, ...over });

describe("the tooltip on each state indicator a card draws", () => {
  it.each([
    ["checks pass", pull(), "#7 checks pass"],
    ["failing", pull({ checks: "failing" }), "#7 checks failing"],
    ["pending", pull({ checks: "pending" }), "#7 checks pending"],
    ["merged", pull({ merged: true }), "#7 merged"],
    ["queued", pull({ queued: true }), "#7 queued, checks pass"],
    ["closed", pull({ closed: true }), "#7 closed"],
    ["review threads", pull({ threads: 3 }), "#7 checks pass, 3 open review threads"],
  ])("names a PR chip's %s state", (_name, p, title) => {
    expect(draw({ prs: [p] })).toContain(`title="${title}"`);
  });

  it("names a card on a lifecycle machine", () => {
    expect(draw({ live: { machine: "in-progress", state: "red_proven", at: 0 } })).toContain('<span class="p" title="on the in-progress machine"></span>');
  });

  it("names a card on a mapped machine and its source", () => {
    expect(draw({ live: { machine: "ci", state: "running", at: 0, source: "GitHub" } })).toContain('title="mapped from GitHub"');
  });

  it("says a card moved now while its machine event is fresh, and not once it is old", () => {
    const live = { machine: "in-progress", state: "red_proven", at: 900 };

    expect(draw({ live }, 0, 960)).toContain('title="on the in-progress machine, moved now"');
    expect(draw({ live }, 0, 2000)).not.toContain("moved now");
    expect(draw({ live: { ...live, source: "GitHub" } }, 0, 960)).toContain('title="mapped from GitHub, moved now"');
  });

  it("names the open dependencies a card waits on, with their count", () => {
    expect(draw({ openDeps: 2 })).toContain('title="2 open dependencies"');
    expect(draw({ openDeps: 1 })).toContain('title="1 open dependency"');
  });

  it("names the outlines a hovered card draws on the cards it holds and waits on, and no other card does", () => {
    expect(draw({}, 0, 1000, "self")).toContain('title="outlined: Waiting tasks it holds and open tasks it waits on"');
    expect(draw({}, 0, 1000, "holds")).not.toContain("outlined:");
    expect(draw({}, 0, 1000, "waits")).not.toContain("outlined:");
    expect(draw()).not.toContain("outlined:");
  });

  it("names the Waiting tasks a card holds, with their count", () => {
    expect(draw({}, 3)).toContain('title="holds 3 Waiting tasks"');
    expect(draw({}, 1)).toContain('title="holds 1 Waiting task"');
  });
});
