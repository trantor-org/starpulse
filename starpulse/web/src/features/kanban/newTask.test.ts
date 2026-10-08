import { describe, expect, it } from "vitest";
import { EMPTY_DRAFT, createBody, createOutcome, postCreate, newTaskKey, type NewTaskDraft } from "./newTask";

const answer = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status });
const FULL: NewTaskDraft = {
  title: " Write the quickstart ", description: "Explain the lanes.\n", priority: "High", labels: "docs, ui ,", milestone: "m-1",
  assignee: "@agent-fast-low", dependencies: "task-1", acceptanceCriteria: ["Names every lane", " ", "Creates a task"],
};

describe("the body of a create", () => {
  it("carries every filled field, trimmed, with labels and dependencies split on commas and blank criteria dropped", () => {
    expect(createBody(FULL)).toEqual({
      title: "Write the quickstart", description: "Explain the lanes.", priority: "High", labels: ["docs", "ui"], milestone: "m-1",
      assignee: "@agent-fast-low", dependencies: ["task-1"], acceptanceCriteria: ["Names every lane", "Creates a task"],
    });
  });

  it("is the title alone when nothing else was filled", () => {
    expect(createBody({ ...EMPTY_DRAFT, title: "Write the docs" })).toEqual({ title: "Write the docs" });
  });
});

describe("creating a task", () => {
  it("posts the draft and returns the id the board gave it", async () => {
    let sent: { url: string; init?: RequestInit } | null = null;
    const fetcher = async (url: string, init?: RequestInit) => { sent = { url, init }; return new Response(JSON.stringify({ task: "TASK-1" }), { status: 201 }); };

    expect(await postCreate(FULL, fetcher)).toEqual({ ok: true, task: "TASK-1" });
    expect(sent!.url).toBe("/api/tasks");
    expect(sent!.init?.method).toBe("POST");
    expect(JSON.parse(String(sent!.init?.body))).toEqual(createBody(FULL));
  });

  it("returns a refusal's reason and skill as a value", async () => {
    const draft = { ...EMPTY_DRAFT, title: "x" };
    expect(await postCreate(draft, answer(409, { error: "the board is read-only", skill: "completing-tasks" }))).toEqual({ ok: false, reason: "the board is read-only", skill: "completing-tasks" });
    expect(await postCreate(draft, answer(404, { error: "this board does not create tasks" }))).toEqual({ ok: false, reason: "this board does not create tasks", skill: "" });
  });

  it("names the status when a refusal carries no reason, and says the writer could not be reached on a network failure", async () => {
    const draft = { ...EMPTY_DRAFT, title: "x" };
    expect(await postCreate(draft, answer(500, {}))).toMatchObject({ ok: false, reason: expect.stringContaining("500") });
    const down = async () => { throw new TypeError("offline"); };

    expect(await postCreate(draft, down)).toMatchObject({ ok: false, reason: expect.stringContaining("could not be reached") });
  });
});

describe("what the form holds after a create", () => {
  it("empties the draft and names the new task when the board created it", () => {
    expect(createOutcome(FULL, { ok: true, task: "TASK-1" })).toEqual({ draft: EMPTY_DRAFT, refused: null, created: "TASK-1" });
  });

  it("keeps the whole draft with the reason when the board refused", () => {
    expect(createOutcome(FULL, { ok: false, reason: "the board is read-only", skill: "" })).toEqual({ draft: FULL, refused: "the board is read-only", created: null });
  });
});

describe("the form's keys", () => {
  it("creates on Ctrl or Cmd+Enter, cancels on Escape, leaves a plain Enter to the field, and does nothing while a create runs", () => {
    expect(newTaskKey("Enter", true, false)).toBe("submit");
    expect(newTaskKey("Enter", false, false)).toBeNull();
    expect(newTaskKey("Escape", false, false)).toBe("cancel");
    expect(newTaskKey("a", true, false)).toBeNull();
    expect(newTaskKey("Enter", true, true)).toBeNull();
    expect(newTaskKey("Escape", false, true)).toBeNull();
  });
});
