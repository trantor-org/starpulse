import { describe, expect, it } from "vitest";
import { archiveDialogKey, archiveKey, archiveWarnings, postArchive, withoutArchived } from "./archive";
import { COLUMNS, NO_PREFS, layout, type KanbanTask } from "./kanban";

const task = (id: string, lane: string, over: Partial<KanbanTask> = {}): KanbanTask => ({
  id, title: id, lane, milestone: "m-89", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null,
  released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [], ...over,
});
const pull = (over = {}) => ({ number: 7, url: "http://pr/7", checks: "pass" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false, ...over });
const reply = (status: number, body: object) => async () => new Response(JSON.stringify(body), { status });

describe("posting an archive", () => {
  it("posts the task and the typed reason to /api/archive", async () => {
    const seen: { url: string; init?: RequestInit }[] = [];
    const fetcher = async (url: string, init?: RequestInit) => { seen.push({ url, init }); return new Response("{}", { status: 200 }); };

    const result = await postArchive("TASK-9", "superseded by m-80", fetcher);

    expect(result).toEqual({ ok: true });
    expect(seen).toHaveLength(1);
    expect(seen[0].url).toBe("/api/archive");
    expect(seen[0].init?.method).toBe("POST");
    expect(JSON.parse(String(seen[0].init?.body))).toEqual({ task: "TASK-9", reason: "superseded by m-80" });
  });

  it("returns the writer's refusal with its skill", async () => {
    const result = await postArchive("TASK-9", "", reply(409, { error: "timed out after 30 s; the task was not archived.", skill: "completing-tasks" }));

    expect(result).toEqual({ ok: false, reason: "timed out after 30 s; the task was not archived.", skill: "completing-tasks" });
  });

  it("explains an unreachable server and a body-less failure instead of throwing", async () => {
    const down = await postArchive("TASK-9", "", async () => { throw new TypeError("offline"); });
    const bare = await postArchive("TASK-9", "", async () => new Response("<html>", { status: 502 }));

    expect(down).toMatchObject({ ok: false, reason: expect.stringContaining("could not be reached") });
    expect(bare).toMatchObject({ ok: false, reason: expect.stringContaining("502") });
  });
});

describe("what leaves the board when a task is archived", () => {
  const cards = [task("TASK-1", "ready"), task("TASK-2", "ready"), task("TASK-3", "review")];
  const count = (list: KanbanTask[], lane: string) => layout(list, {}, NO_PREFS, 0).columns.find((c) => c.id === lane)?.count;

  it("takes the card out of its column and drops the column's count and the open total", () => {
    const after = withoutArchived(cards, new Set(["TASK-1"]));

    expect(after.map((t) => t.id)).toEqual(["TASK-2", "TASK-3"]);
    expect(count(cards, "ready")).toBe(2);
    expect(count(after, "ready")).toBe(1);
    expect(layout(after, {}, NO_PREFS, 0).open).toBe(2);
  });

  it("keeps every card when nothing was archived, as after a refusal", () => {
    expect(withoutArchived(cards, new Set())).toBe(cards);
    expect(count(withoutArchived(cards, new Set()), "ready")).toBe(2);
  });
});

describe("the archive confirm's warnings", () => {
  it("warns about an open pull request and ignores a merged one", () => {
    expect(archiveWarnings(task("TASK-1", "review", { prs: [pull()] })).pull?.number).toBe(7);
    expect(archiveWarnings(task("TASK-1", "review", { prs: [pull({ merged: true })] })).pull).toBeNull();
  });

  it("warns about a live agent session only while the task is in progress on a machine", () => {
    const live = { machine: "in-progress", state: "implementing", at: 100 };

    expect(archiveWarnings(task("TASK-1", "in_progress", { live })).session).toEqual(live);
    expect(archiveWarnings(task("TASK-1", "ready", { live })).session).toBeNull();
    expect(archiveWarnings(task("TASK-1", "in_progress")).session).toBeNull();
  });

  it("has no warning for a task with neither", () => {
    for (const lane of COLUMNS) expect(archiveWarnings(task("TASK-1", lane))).toEqual({ pull: null, session: null });
  });
});

describe("the archive confirm's keys", () => {
  it("cancels on Escape, confirms on Ctrl or Cmd+Enter, and ignores both while the archive is running", () => {
    expect(archiveKey("Escape", false, false, false)).toBe("cancel");
    expect(archiveKey("Enter", true, false, false)).toBe("confirm");
    expect(archiveKey("Enter", false, true, false)).toBe("confirm");
    expect(archiveKey("Enter", false, false, false)).toBeNull();
    expect(archiveKey("Escape", false, false, true)).toBeNull();
    expect(archiveKey("Enter", true, false, true)).toBeNull();
  });
});

describe("the dialog's key", () => {
  it("differs from the task Modal's bare-id key, which sits beside it in the same parent", () => {
    expect(archiveDialogKey("TASK-7")).not.toBe("TASK-7");
  });
});
