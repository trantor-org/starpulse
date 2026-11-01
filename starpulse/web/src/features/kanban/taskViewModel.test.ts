import { describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanbanModel";
import { changedFields, ciHistory, detailFields, docLinks, fetchDoc, fetchDocs, fetchMilestone, editKey, fetchRecord, labelRuleError, markdown, menuKey, postComment, saveSection, saveTask, SECTION_FIELDS, setDetailField, taskActivity, taskBody, toggleItem, type MenuState, type TaskRecord } from "./taskViewModel";

const record = {
  title: "T", profile: "@agent-standard-high", priority: "High", labels: ["needs-review"], milestone: "m-89", dependencies: ["TASK-1"],
  description: "d", plan: "1. a", notes: "n", acceptanceCriteria: [{ n: 1, text: "a gate", checked: true }], definitionOfDone: [],
};
const reply = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status });

describe("taskActivity", () => {
  const step = (event: string, state: string, at: number) => ({ event, state, at });
  const machineTask = (machines: KanbanTask["machines"]) => ({ id: "TASK-1", machines }) as KanbanTask;
  const at = (created: string) => Date.parse(created.replace(" ", "T")) / 1000;

  it("draws checkpoint evidence, the claim and the board's own notes as activity, and keeps the rest as comments", () => {
    const { activity, comments } = taskActivity(machineTask([]), [
      { created: "2026-10-26 10:20", author: "agent", text: "**Session Link:** https://claude.ai/code/session_01SDztUtQe9r — local" },
      { created: "2026-10-26 10:28", author: "agent", text: "Verified AC #2: `pnpm test` GREEN" },
      { created: "2026-10-26 10:41", author: "Adin", text: "Drop AC #4." },
      { created: "2026-10-26 10:56", author: "starpulse/task-actor", text: "Every dependency has merged." },
    ]);

    expect(activity.map(({ kind, who, ac, body }) => ({ kind, who, ac, body }))).toEqual([
      { kind: "system", who: "agent", ac: undefined, body: "Claimed by session [`01SDztUt`](https://claude.ai/code/session_01SDztUtQe9r)" },
      { kind: "checkpoint", who: "agent", ac: 2, body: "`pnpm test` GREEN" },
      { kind: "system", who: "starpulse", ac: undefined, body: "Every dependency has merged." },
    ]);
    expect(activity[1].at).toBe(at("2026-10-26 10:28"));
    expect(comments.map(({ kind, who, body }) => ({ kind, who, body }))).toEqual([{ kind: "comment", who: "Adin", body: "Drop AC #4." }]);
  });

  it("groups the machines' lifecycle steps per machine, oldest first, apart from the flat activity and without the harness's tool calls or a checkpoint's echo", () => {
    const evidence = at("2026-10-26 10:28");
    const { activity, machines } = taskActivity(machineTask([
      { machine: "deliver", state: "pr_ready", at: evidence + 60, trail: [step("AC_CHECKPOINTED", "start", evidence), step("PR_OPENED", "pr_opened", evidence + 30), step("PR_READY", "pr_ready", evidence + 60)] },
      { machine: "build", state: "worktree_ready", at: evidence - 60, trail: [step("WORKTREE_READY", "worktree_ready", evidence - 60)] },
      { machine: "harness", state: "active", at: evidence + 1, trail: [step("TOOL_USED", "active", evidence + 1)] },
    ]), [{ created: "2026-10-26 10:28", text: "Verified AC #1: green" }]);

    expect(activity.map(({ kind, who, body }) => [kind, who, body])).toEqual([["checkpoint", "agent", "green"]]);
    expect(machines.map(({ machine, state, at, steps }) => [machine, state, at, steps.map((s) => s.body)])).toEqual([
      ["build", "worktree_ready", evidence - 60, ["`WORKTREE_READY` → worktree ready"]],
      ["deliver", "pr_ready", evidence + 60, ["`PR_OPENED` → pr opened", "`PR_READY` → pr ready"]],
    ]);
  });

  it("keeps a checkpoint's command line as its body and its fenced output tail apart as detail", () => {
    const { activity } = taskActivity(machineTask([]), [
      { created: "2026-10-26 09:11", text: "Verified AC #1: `pnpm exec vitest run` exited 0\n\n```\n\n Test Files  1 passed (1)\n```" },
    ]);

    expect(activity.map(({ body, detail }) => ({ body, detail }))).toEqual([{ body: "`pnpm exec vitest run` exited 0", detail: "Test Files  1 passed (1)" }]);
  });

  it("keeps a failed checkpoint's fenced output apart as detail under Comments", () => {
    const { comments } = taskActivity(machineTask([]), [
      { created: "2026-10-26 09:11", text: "AC #1 not verified: `vitest` exited 1\n\n```\nError: no such file\n```" },
    ]);

    expect(comments.map(({ body, detail }) => ({ body, detail }))).toEqual([{ body: "AC #1 not verified: `vitest` exited 1", detail: "Error: no such file" }]);
  });

  it("is empty for a task with no steps and no comments", () => {
    expect(taskActivity(machineTask([{ machine: "in-progress", state: "ready", at: 0, trail: [] }]), [])).toEqual({ activity: [], machines: [], comments: [] });
  });
});

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

describe("postComment", () => {
  it("posts the comment on the edit endpoint naming the title as it stands, changing no field", async () => {
    let sent: { url: string; body: unknown } | undefined;
    const ok = await postComment("TASK-1", record as TaskRecord, "  looks good  ", async (url, init) => {
      sent = { url, body: JSON.parse(String(init?.body)) };
      return new Response("{}");
    });

    expect(ok).toBe(true);
    expect(sent?.url).toBe("/api/edit");
    expect(sent?.body).toMatchObject({ task: "TASK-1", base: { title: "T" }, changes: { title: "T" }, comment: "looks good" });
  });

  it("reports a refused or unreachable write as not posted", async () => {
    expect(await postComment("TASK-1", record as TaskRecord, "x", reply(409, { error: "stale" }))).toBe(false);
    expect(await postComment("TASK-1", record as TaskRecord, "x", async () => { throw new Error("offline"); })).toBe(false);
  });
});

describe("saving an edited task", () => {
  const base = record as TaskRecord;

  it("posts only changed fields and the matching base values in one request", async () => {
    const draft = { ...base, title: "New title", labels: ["ui", "needs-review"] };
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ task: "TASK-9", changed: ["title", "labels"] })));

    const result = await saveTask("TASK-9", base, draft, {}, fetcher);

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/api/edit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        task: "TASK-9",
        base: { title: "T", labels: ["needs-review"] },
        changes: { title: "New title", labels: ["ui", "needs-review"] },
        comment: "",
        actor: "operator",
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

describe("saving one section", () => {
  const base = record as TaskRecord;
  const ok = () => vi.fn(async () => new Response(JSON.stringify({ task: "TASK-9" })));
  const sent = (fetcher: ReturnType<typeof ok>) => JSON.parse((fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body);

  it("sends only that section's diff although the draft differs elsewhere", async () => {
    const draft = { ...base, title: "Other title", description: "new text", plan: "2. b" };
    const fetcher = ok();

    const result = await saveSection("TASK-9", "description", base, draft, {}, fetcher);

    expect(fetcher).toHaveBeenCalledOnce();
    expect(sent(fetcher)).toMatchObject({ base: { description: "d" }, changes: { description: "new text" } });
    expect(Object.keys(sent(fetcher).changes)).toEqual(["description"]);
    expect(result).toMatchObject({ ok: true, changed: ["description"] });
  });

  it("writes Details' profile, priority, labels and milestone and nothing else", async () => {
    const draft = { ...base, profile: "@agent-light-low", priority: "Low", milestone: "m-90", labels: ["x"], notes: "z" };
    const fetcher = ok();

    await saveSection("TASK-9", "details", base, draft, {}, fetcher);

    expect(SECTION_FIELDS.details).toEqual(["profile", "priority", "labels", "milestone"]);
    expect(Object.keys(sent(fetcher).changes)).toEqual(["profile", "priority", "labels", "milestone"]);
  });

  it("sends a criterion added in the editor without a number, which the board assigns", async () => {
    const draft = { ...base, acceptanceCriteria: [...base.acceptanceCriteria, { n: 0, text: "a new gate", checked: false }] };
    const fetcher = ok();

    await saveSection("TASK-9", "acceptanceCriteria", base, draft, {}, fetcher);

    expect(sent(fetcher).changes.acceptanceCriteria).toEqual([{ n: 1, text: "a gate", checked: true }, { text: "a new gate", checked: false }]);
  });
});

describe("a checklist row left blank", () => {
  it("is dropped from the write, which the board refuses for blank text", async () => {
    const base = record as TaskRecord;
    const draft = { ...base, acceptanceCriteria: [...base.acceptanceCriteria, { n: 0, text: "  ", checked: false }] };
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ task: "TASK-9" })));

    const result = await saveSection("TASK-9", "acceptanceCriteria", base, draft, {}, fetcher);

    expect(fetcher).not.toHaveBeenCalled();
    expect(result).toMatchObject({ ok: true, changed: [], record: base });
  });
});

describe("toggling a checkbox without an editor", () => {
  const open = { ...record, acceptanceCriteria: [{ n: 1, text: "a gate", checked: false }], definitionOfDone: [{ n: 1, text: "done item", checked: false }] } as TaskRecord;

  it("flips one item and leaves the rest of the record alone", () => {
    const toggled = toggleItem(open, "definitionOfDone", 1, true);

    expect(toggled.definitionOfDone).toEqual([{ n: 1, text: "done item", checked: true }]);
    expect(toggled.acceptanceCriteria).toBe(open.acceptanceCriteria);
  });

  it("writes the checklist alone, with no comment for a Definition of done item", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ task: "TASK-9" })));

    await saveSection("TASK-9", "definitionOfDone", open, toggleItem(open, "definitionOfDone", 1, true), {}, fetcher);

    const body = JSON.parse((fetcher.mock.calls[0] as unknown as [string, { body: string }])[1].body);
    expect(body).toEqual({ task: "TASK-9", base: { definitionOfDone: open.definitionOfDone }, changes: { definitionOfDone: [{ n: 1, text: "done item", checked: true }] }, comment: "", actor: "operator" });
  });

  it("asks for evidence before writing a newly checked acceptance criterion", async () => {
    const fetcher = vi.fn();

    expect(await saveSection("TASK-9", "acceptanceCriteria", open, toggleItem(open, "acceptanceCriteria", 1, true), {}, fetcher)).toMatchObject({ ok: false, missingEvidence: [1] });
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe("edit keyboard actions", () => {
  it("cancels the open editor on Escape and saves on Ctrl/Command+Enter", () => {
    expect(editKey("Escape", false, false)).toBe("cancel");
    expect(editKey("Enter", true, false)).toBe("save");
    expect(editKey("Enter", false, true)).toBe("save");
    expect(editKey("Enter", false, false)).toBeNull();
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
      { kind: "p", text: "one\ntwo" }, { kind: "h", text: "Head" }, { kind: "pre", lang: "yaml", text: "a: 1\n\nb: 2" }, { kind: "p", text: "after" },
    ]);
  });

  it("closes an unterminated fence at the end and draws nothing for an empty description", () => {
    expect(markdown("```\nopen")).toEqual([{ kind: "pre", lang: "", text: "open" }]);
    expect(markdown("")).toEqual([]);
  });

  it("reads a GFM table's header, alignment and rows, and ends it at the first line without a pipe", () => {
    expect(markdown("| a | b |\n|:-- | --: |\n| 1 | 2 |\n| 3 | 4 |\nafter")).toEqual([
      { kind: "table", head: ["a", "b"], right: [false, true], rows: [["1", "2"], ["3", "4"]] },
      { kind: "p", text: "after" },
    ]);
  });
});

describe("taskBody", () => {
  it("removes the creation sections and the Assignee line, and keeps a fenced heading", () => {
    const body = taskBody({
      ...(record as TaskRecord),
      description: "Intro.\n\n## Duplicate Search\n\nnone\n\n## Scope\n\nDo it.\n\n```md\n## ADR Needed\n```\n\n## ADR Needed\n\nNo",
      notes: "**Assignee:** abc\nKept note",
    });

    expect(body.description).toBe("Intro.\n\n## Scope\n\nDo it.\n\n```md\n## ADR Needed\n```");
    expect(body.notes).toBe("Kept note");
  });
});

describe("a task's CI history", () => {
  const url = (n: number) => `https://github.com/o/r/pull/${n}`;
  const step = (n: number | null, kind: string, event: string, state: string, at: number) =>
    ({ event, state, at, ...(n === null ? {} : { id: `ci:${url(n)}:${kind}` }) });
  const pull = (number: number) => ({ number, repo: "o/r", url: url(number), checks: "pass" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false });
  // PR 12: pushed, failed, re-run, passed, conflicted, rebased, passed, merged. PR 15 opens after it and is failing after two pushes.
  const trail = [
    step(12, "opened", "PR_OPENED", "opened", 1), step(12, "push:a", "PUSHED", "running", 2), step(12, "checks:a", "CHECKS_FAILED", "failing", 3), step(12, "rerun", "RERUN", "running", 4),
    step(12, "checks:b", "CHECKS_PASSED", "passing", 5), step(12, "conflict", "CONFLICTED", "conflicting", 6), step(12, "rebase", "REBASED", "running", 7), step(12, "checks:c", "CHECKS_PASSED", "passing", 8),
    step(12, "merged", "MERGED", "merged", 9),
    step(15, "opened", "PR_OPENED", "opened", 10), step(15, "push:a", "PUSHED", "running", 11), step(15, "checks:a", "CHECKS_FAILED", "failing", 12), step(15, "push:b", "PUSHED", "running", 13), step(15, "checks:b", "CHECKS_FAILED", "failing", 14),
  ];
  const task = (over: Partial<KanbanTask>) => ({ prs: [pull(15), pull(12)], machines: [{ machine: "ci", state: "failing", at: 14, source: "GitHub", trail }], ...over }) as KanbanTask;

  it("counts each pull request's runs, re-runs, rebases and conflicts and names the state its trail left it in, then sums the task", () => {
    expect(ciHistory(task({}))).toEqual({
      pulls: [
        { number: 12, url: url(12), runs: 1, reruns: 1, rebases: 1, conflicts: 1, state: "merged" },
        { number: 15, url: url(15), runs: 2, reruns: 0, rebases: 0, conflicts: 0, state: "failing" },
      ],
      total: { runs: 3, reruns: 1, rebases: 1, conflicts: 1 },
    });
  });

  it("attributes a step to the pull request its id names, so a repeated PR_OPENED opens no second pull request", () => {
    const doubled = [trail[0], trail[1], trail[0], trail[1]];
    expect(ciHistory(task({ prs: [pull(12)], machines: [{ machine: "ci", state: "running", at: 2, trail: doubled }] }))?.pulls)
      .toEqual([{ number: 12, url: url(12), runs: 2, reruns: 0, rebases: 0, conflicts: 0, state: "running" }]);
  });

  it("keeps a pull request absent from the task's list from shifting another's counts, and links it by the url its id holds", () => {
    const history = ciHistory(task({ prs: [pull(15)] }));
    expect(history?.pulls.map((p) => [p.number, p.url, p.runs])).toEqual([[12, url(12), 1], [15, url(15), 2]]);
  });

  it("has no history for a task outside the ci machine, and counts a step without an id on the pull request before it", () => {
    expect(ciHistory(task({ machines: [{ machine: "in-progress", state: "pr_opened", at: 1, trail }] }))).toBeNull();
    const bare = [step(null, "", "PUSHED", "running", 2), step(null, "", "CHECKS_FAILED", "failing", 3)];
    expect(ciHistory(task({ prs: [], machines: [{ machine: "ci", state: "running", at: 3, trail: bare }] }))?.pulls)
      .toEqual([{ number: null, url: null, runs: 1, reruns: 0, rebases: 0, conflicts: 0, state: "failing" }]);
  });
});

describe("labelRuleError", () => {
  it("refuses a date, an id, a long label and a field's prefix, and accepts a short kebab-case word", () => {
    expect(labelRuleError("weekly-code-audit-2026-10-25-follow-up")).toMatch(/3 words, 24 chars/);
    expect(labelRuleError("TASK-12")).toMatch(/not kebab-case/);
    expect(labelRuleError("a".repeat(25))).toMatch(/25 chars/);
    expect(labelRuleError("audit-signal-hotspot-a1597d40")).toMatch(/4 words/);
    expect(labelRuleError("release-2026")).toMatch(/carries a date or id/);
    expect(labelRuleError("size-3")).toBe("size- is a field; set size above.");
    expect(labelRuleError("follow-up")).toBe("");
    expect(labelRuleError("a".repeat(24))).toBe("");
  });
});

describe("detailFields", () => {
  it("reads kind, size, area and mode from their prefixed labels and leaves the free-form ones as chips", () => {
    const labels = ["kind-execute", "size-5", "needs-review", "area-starpulse", "mode-attended", "trial-a", "follow-up"];
    expect(detailFields(labels)).toEqual({ kind: "execute", size: "5", area: "starpulse", mode: "attended", chips: ["needs-review", "follow-up"] });
  });

  it("draws the first of two labels sharing a prefix and an empty value for a prefix with none", () => {
    expect(detailFields(["size-3", "size-8"])).toMatchObject({ kind: "", size: "3", chips: [] });
  });
});

describe("setDetailField", () => {
  it("replaces a field's label in place, drops a second one, and removes it for an empty value", () => {
    expect(setDetailField(["kind-execute", "x", "size-3", "size-8"], "size", "5")).toEqual(["kind-execute", "x", "size-5"]);
    expect(setDetailField(["x", "mode-attended"], "mode", "")).toEqual(["x"]);
    expect(setDetailField(["x"], "area", "docs")).toEqual(["x", "area-docs"]);
  });
});

describe("docLinks", () => {
  const milestone = { id: "m-89", title: "Task dialog", description: "d", specs: ["doc-993 — Task dialog redesign"] };
  const docs = [{ id: "doc-993", title: "Task dialog redesign", type: "specification" }, { id: "doc-12", title: "Working notes", type: "other" }];

  it("lists the milestone, its spec, then each linked doc once, titled from the board's list", () => {
    const links = docLinks({ milestone: "m-89", documentation: ["docs/specs/doc-993 - Task dialog redesign.md", "docs/doc-12 - Working notes.md"] }, milestone, docs);

    expect(links).toEqual([
      { kind: "Milestone", id: "m-89", title: "Task dialog", openable: true },
      { kind: "Spec", id: "doc-993", title: "Task dialog redesign", openable: true },
      { kind: "Doc", id: "doc-12", title: "Working notes", openable: true },
    ]);
  });

  it("names a specification the milestone does not list a Spec, and leaves a file the board does not serve closed", () => {
    const links = docLinks({ milestone: "", documentation: ["docs/doc-993 - Task dialog redesign.md", "docs/doc-404 - Gone.md", "notes.md"] }, null, docs);

    expect(links).toEqual([
      { kind: "Spec", id: "doc-993", title: "Task dialog redesign", openable: true },
      { kind: "Doc", id: "doc-404", title: "Gone", openable: false },
      { kind: "Doc", id: "", title: "notes", openable: false },
    ]);
  });

  it("keeps the milestone row closed until the milestone is read, and has no rows for a task with neither", () => {
    expect(docLinks({ milestone: "m-89" }, null, [])).toEqual([{ kind: "Milestone", id: "m-89", title: "m-89", openable: false }]);
    expect(docLinks({ milestone: "" }, null, docs)).toEqual([]);
  });
});

describe("the doc reads", () => {
  it("unwrap the board's milestone, list and doc, and give nothing when the board refuses", async () => {
    expect(await fetchMilestone("m-89", reply(200, { milestone: { id: "m-89" } }) as never)).toEqual({ id: "m-89" });
    expect(await fetchDocs(reply(200, { docs: [{ id: "doc-1" }] }) as never)).toEqual([{ id: "doc-1" }]);
    expect(await fetchDoc("doc-1", reply(200, { doc: { id: "doc-1", body: "b" } }) as never)).toEqual({ id: "doc-1", body: "b" });
    expect(await fetchMilestone("m-1", reply(404, { error: "no" }) as never)).toBeNull();
    expect(await fetchDocs((async () => { throw new Error("offline"); }) as never)).toEqual([]);
  });
});
