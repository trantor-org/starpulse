import { describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanban";
import { changedFields, ciHistory, discardMessage, editKey, fetchRecord, markdown, menuKey, saveTask, type MenuState, type TaskRecord } from "./taskView";

const record = {
  title: "T", profile: "@agent-standard-high", priority: "High", labels: ["needs-human"], milestone: "m-89", dependencies: ["TASK-1"],
  description: "d", plan: "1. a", notes: "n", acceptanceCriteria: [{ n: 1, text: "a gate", checked: true }], definitionOfDone: [],
};
const reply = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status });

describe("fetching a task's record", () => {
  it("asks /api/task/<id> and returns the record the server sends", async () => {
    let asked = "";
    const got = await fetchRecord("TASK-2712", async (url) => { asked = url; return new Response(JSON.stringify({ task: "TASK-2712", record })); });

    expect(asked).toBe("/api/task/TASK-2712");
    expect(got).toEqual(record);
  });

  it("returns null when the board cannot read the task or the request fails", async () => {
    expect(await fetchRecord("TASK-1", reply(404, { error: "no" }))).toBeNull();
    expect(await fetchRecord("TASK-1", async () => { throw new Error("offline"); })).toBeNull();
  });
});

describe("saving an edited task", () => {
  const base = record as TaskRecord;

  it("posts only changed fields and the matching base values in one request", async () => {
    const draft = { ...base, title: "New title", labels: ["ui", "needs-human"] };
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ task: "TASK-9", changed: ["title", "labels"] })));

    const result = await saveTask("TASK-9", base, draft, {}, fetcher);

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/api/edit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        task: "TASK-9",
        base: { title: "T", labels: ["needs-human"] },
        changes: { title: "New title", labels: ["ui", "needs-human"] },
        comment: "",
      }),
    });
    expect(result).toMatchObject({ ok: true, changed: ["title", "labels"], record: draft });
    expect(changedFields(base, draft).fields).toEqual(["title", "labels"]);
  });

  it("retains the draft and marks refused fields on a stale or writer refusal", async () => {
    const draft = { ...base, title: "Mine", notes: "my note" };
    const stale = await saveTask("TASK-9", base, draft, {}, reply(409, { error: "changed elsewhere", stale: ["title"] }));
    const refused = await saveTask("TASK-9", base, draft, {}, reply(409, { error: "run the gate", skill: "authoring-docs" }));

    expect(stale).toEqual({ ok: false, reason: "changed elsewhere", skill: "", fields: ["title"], record: draft });
    expect(refused).toEqual({ ok: false, reason: "run the gate", skill: "authoring-docs", fields: ["title", "notes"], record: draft });
  });

  it("requires evidence for a newly checked acceptance criterion before making a request", async () => {
    const open = { ...base, acceptanceCriteria: [{ n: 1, text: "a gate", checked: false }] };
    const draft = { ...open, acceptanceCriteria: [{ n: 1, text: "a gate", checked: true }] };
    const fetcher = vi.fn();

    expect(await saveTask("TASK-9", open, draft, {}, fetcher)).toEqual({ ok: false, missingEvidence: [1], record: draft });
    expect(fetcher).not.toHaveBeenCalled();
    await saveTask("TASK-9", open, draft, { 1: "Vitest failed before implementation" }, fetcher.mockResolvedValue(new Response(JSON.stringify({ changed: ["acceptanceCriteria"] }))));
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({ comment: "AC #1: Vitest failed before implementation" });
  });
});

describe("edit keyboard actions", () => {
  it("asks before discarding dirty edits, cancels a clean edit, and saves on Ctrl/Command+Enter", () => {
    expect(editKey("Escape", false, false, true)).toBe("discard");
    expect(editKey("Escape", false, false, false)).toBe("cancel");
    expect(editKey("Enter", true, false, true)).toBe("save");
    expect(editKey("Enter", false, true, true)).toBe("save");
    expect(editKey("Enter", false, false, true)).toBeNull();
    expect(discardMessage(1)).toBe("Discard 1 change?");
    expect(discardMessage(3)).toBe("Discard 3 changes?");
  });
});

describe("the Move to menu's keyboard", () => {
  const closed: MenuState = { open: false, on: -1 };
  const all = [true, true, true];

  it("opens on ArrowDown at the first item and on ArrowUp at the last", () => {
    expect(menuKey(closed, "ArrowDown", all)).toEqual({ state: { open: true, on: 0 }, pick: null, handled: true });
    expect(menuKey(closed, "ArrowUp", all)).toEqual({ state: { open: true, on: 2 }, pick: null, handled: true });
  });

  it("steps through the items with the arrows and wraps at both ends", () => {
    const at = (on: number): MenuState => ({ open: true, on });

    expect(menuKey(at(0), "ArrowDown", all).state.on).toBe(1);
    expect(menuKey(at(2), "ArrowDown", all).state.on).toBe(0);
    expect(menuKey(at(0), "ArrowUp", all).state.on).toBe(2);
  });

  it("picks the highlighted item on Enter and closes", () => {
    expect(menuKey({ open: true, on: 1 }, "Enter", all)).toEqual({ state: { open: false, on: -1 }, pick: 1, handled: true });
  });

  it("keeps the menu open when Enter lands on a disabled item", () => {
    const step = menuKey({ open: true, on: 1 }, "Enter", [true, false, true]);

    expect(step.pick).toBeNull();
    expect(step.state.open).toBe(true);
    expect(step.handled).toBe(true);
  });

  it("closes only the menu on Escape, and lets Escape through when the menu is already closed", () => {
    expect(menuKey({ open: true, on: 1 }, "Escape", all)).toEqual({ state: { open: false, on: -1 }, pick: null, handled: true });
    expect(menuKey(closed, "Escape", all).handled).toBe(false);
  });

  it("leaves a menu with no items closed", () => {
    expect(menuKey(closed, "ArrowDown", []).state.open).toBe(false);
  });
});

describe("markdown", () => {
  it("keeps a fenced block whole across its blank lines and a paragraph's line breaks", () => {
    expect(markdown("one\ntwo\n\n## Head\n\n```yaml\na: 1\n\nb: 2\n```\nafter")).toEqual([
      { kind: "p", text: "one\ntwo" }, { kind: "h", text: "Head" }, { kind: "pre", text: "a: 1\n\nb: 2" }, { kind: "p", text: "after" },
    ]);
  });

  it("closes an unterminated fence at the end and draws nothing for an empty description", () => {
    expect(markdown("```\nopen")).toEqual([{ kind: "pre", text: "open" }]);
    expect(markdown("")).toEqual([]);
  });
});

describe("a task's CI history", () => {
  const step = (event: string, state: string, at: number) => ({ event, state, at });
  const pull = (number: number) => ({ number, url: `http://pr/${number}`, checks: "pass" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false });
  // PR 12: pushed, failed, re-run, passed, conflicted, rebased, passed, merged. PR 15 opens after it and is failing after two pushes.
  const trail = [
    step("PR_OPENED", "opened", 1), step("PUSHED", "running", 2), step("CHECKS_FAILED", "failing", 3), step("RERUN", "running", 4),
    step("CHECKS_PASSED", "passing", 5), step("CONFLICTED", "conflicting", 6), step("REBASED", "running", 7), step("CHECKS_PASSED", "passing", 8),
    step("MERGED", "merged", 9),
    step("PR_OPENED", "opened", 10), step("PUSHED", "running", 11), step("CHECKS_FAILED", "failing", 12), step("PUSHED", "running", 13), step("CHECKS_FAILED", "failing", 14),
  ];
  const task = (over: Partial<KanbanTask>) => ({ prs: [pull(15), pull(12)], machines: [{ machine: "ci", state: "failing", at: 14, source: "GitHub", trail }], ...over }) as KanbanTask;

  it("counts each pull request's runs, re-runs, rebases and conflicts and names the state its trail left it in, then sums the task", () => {
    expect(ciHistory(task({}))).toEqual({
      pulls: [
        { number: 12, url: "http://pr/12", runs: 1, reruns: 1, rebases: 1, conflicts: 1, state: "merged" },
        { number: 15, url: "http://pr/15", runs: 2, reruns: 0, rebases: 0, conflicts: 0, state: "failing" },
      ],
      total: { runs: 3, reruns: 1, rebases: 1, conflicts: 1 },
    });
  });

  it("has no history for a task outside the ci machine, and counts a trail that begins mid pull request as one", () => {
    expect(ciHistory(task({ machines: [{ machine: "in-progress", state: "pr_opened", at: 1, trail }] }))).toBeNull();
    expect(ciHistory(task({ prs: [], machines: [{ machine: "ci", state: "running", at: 3, trail: trail.slice(1, 3) }] }))?.pulls)
      .toEqual([{ number: null, url: null, runs: 1, reruns: 0, rebases: 0, conflicts: 0, state: "failing" }]);
  });
});
