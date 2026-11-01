import { describe, expect, it, vi } from "vitest";
import { card } from "../../tests/taskViewFixtures";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import { dropProposal, promoteProposal, proposedOf, sectionsOf } from "./proposalsModel";

const roles = { ...LIFECYCLE_ROLES, final: "archived", proposed: "proposed" };

describe("proposedOf", () => {
  it("keeps every Proposed task and no task in another State, the newest first", () => {
    const cards = [
      card("TASK-1", "proposed", { created: 100 }), card("TASK-2", "ready"), card("TASK-3", "proposed", { created: 300 }),
      card("TASK-4", "review"), card("TASK-5", "done"), card("TASK-6", "waiting"), card("TASK-7", "in_progress"), card("TASK-8", "needs_attention"),
    ];
    expect(proposedOf(cards, roles).map((c) => c.id)).toEqual(["TASK-3", "TASK-1"]);
  });

  it("is empty when the lifecycle has no Proposed State", () => {
    expect(proposedOf([card("TASK-1", "proposed")], LIFECYCLE_ROLES)).toEqual([]);
  });
});

describe("sectionsOf", () => {
  it("reads the why before the first heading and the Duplicate Resolution section", () => {
    const text = "Why it matters.\n\nMore.\n\n## Duplicate Search\n\nq1\n\n## Duplicate Resolution\n\nTASK-9: distinct.\n";
    expect(sectionsOf(text)).toEqual({ why: "Why it matters.\n\nMore.", duplicate: "TASK-9: distinct." });
  });

  it("reads the Why section of a templated description, which has no text before its first heading", () => {
    const text = "## Outcome\n\nIt works.\n\n## Why\n\nWaiters wait.\n\n## Duplicate Resolution\n\nTASK-9: distinct.\n";
    expect(sectionsOf(text)).toEqual({ why: "Waiters wait.", duplicate: "TASK-9: distinct." });
  });

  it("reads a description with no headings as all why", () => {
    expect(sectionsOf("Only why.")).toEqual({ why: "Only why.", duplicate: "" });
  });
});

const answer = (ok = true, body: unknown = {}) => ({ ok, json: async () => body }) as Response;

describe("promoteProposal", () => {
  it("sets a changed profile through the edit endpoint, then moves the task to Ready", async () => {
    const fetcher = vi.fn(async () => answer());
    const reply = await promoteProposal("TASK-1", "@agent-standard-high", "", roles, fetcher);
    expect(reply).toEqual({ ok: true });
    const [edit, move] = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(edit[0]).toBe("/api/edit");
    expect(JSON.parse(String(edit[1].body))).toMatchObject({ task: "TASK-1", base: { profile: "" }, changes: { profile: "@agent-standard-high" } });
    expect(move[0]).toBe("/api/move");
    expect(JSON.parse(String(move[1].body))).toMatchObject({ task: "TASK-1", to: "ready" });
  });

  it("writes no edit when the profile is the one the task has", async () => {
    const fetcher = vi.fn(async () => answer());
    await promoteProposal("TASK-1", "@agent-standard-high", "@agent-standard-high", roles, fetcher);
    expect(fetcher.mock.calls.map((c) => (c as unknown as [string])[0])).toEqual(["/api/move"]);
  });

  it("stops at a refused profile edit and moves nothing", async () => {
    const fetcher = vi.fn(async () => answer(false, { error: "unknown profile" }));
    const reply = await promoteProposal("TASK-1", "@agent-x", "", roles, fetcher);
    expect(reply).toMatchObject({ ok: false, reason: "unknown profile" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("dropProposal", () => {
  it("moves the task to the final State", async () => {
    const fetcher = vi.fn(async () => answer());
    expect(await dropProposal("TASK-1", roles, fetcher)).toEqual({ ok: true });
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/move");
    expect(JSON.parse(String(init.body))).toMatchObject({ task: "TASK-1", to: "archived" });
  });
});
