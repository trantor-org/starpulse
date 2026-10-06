import { describe, expect, it } from "vitest";
import { createOutcome, postCreate, newTaskKey } from "./newTask";

const answer = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status });

describe("creating a task", () => {
  it("posts the title and returns the id the board gave it", async () => {
    let sent: { url: string; init?: RequestInit } | null = null;
    const fetcher = async (url: string, init?: RequestInit) => { sent = { url, init }; return new Response(JSON.stringify({ task: "TASK-1" }), { status: 201 }); };

    expect(await postCreate("Write the docs", fetcher)).toEqual({ ok: true, task: "TASK-1" });
    expect(sent!.url).toBe("/api/tasks");
    expect(sent!.init?.method).toBe("POST");
    expect(JSON.parse(String(sent!.init?.body))).toEqual({ title: "Write the docs" });
  });

  it("returns a refusal's reason and skill as a value", async () => {
    expect(await postCreate("x", answer(409, { error: "the board is read-only", skill: "completing-tasks" }))).toEqual({ ok: false, reason: "the board is read-only", skill: "completing-tasks" });
    expect(await postCreate("x", answer(404, { error: "this board does not create tasks" }))).toEqual({ ok: false, reason: "this board does not create tasks", skill: "" });
  });

  it("names the status when a refusal carries no reason, and says the writer could not be reached on a network failure", async () => {
    expect(await postCreate("x", answer(500, {}))).toMatchObject({ ok: false, reason: expect.stringContaining("500") });
    const down = async () => { throw new TypeError("offline"); };

    expect(await postCreate("x", down)).toMatchObject({ ok: false, reason: expect.stringContaining("could not be reached") });
  });
});

describe("what the field holds after a create", () => {
  it("clears the title and names the new task when the board created it", () => {
    expect(createOutcome("Write the docs", { ok: true, task: "TASK-1" })).toEqual({ title: "", refused: null, created: "TASK-1" });
  });

  it("keeps the typed title with the reason when the board refused", () => {
    expect(createOutcome("Write the docs", { ok: false, reason: "the board is read-only", skill: "" })).toEqual({ title: "Write the docs", refused: "the board is read-only", created: null });
  });
});

describe("the field's keys", () => {
  it("submits on Enter and cancels on Escape, and does neither while a create runs", () => {
    expect(newTaskKey("Enter", false)).toBe("submit");
    expect(newTaskKey("Escape", false)).toBe("cancel");
    expect(newTaskKey("a", false)).toBeNull();
    expect(newTaskKey("Enter", true)).toBeNull();
    expect(newTaskKey("Escape", true)).toBeNull();
  });
});
