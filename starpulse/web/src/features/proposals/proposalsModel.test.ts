import { describe, expect, it, vi } from "vitest";
import { card } from "../../tests/taskViewFixtures";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import {
  dropProposal, groupsOf, isPreapproved, kindOf, matchesQuery, modelOf, promoteProposal, proposedOf, sectionsOf, sizeOf, verdictOf,
} from "./proposalsModel";

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

  it("moves a proposal with an open dependency to Waiting", async () => {
    const fetcher = vi.fn(async () => answer());
    await promoteProposal("TASK-1", "", "", { ...roles, waiting: "waiting" }, fetcher, 1);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/move");
    expect(JSON.parse(String(init.body))).toMatchObject({ task: "TASK-1", to: "waiting" });
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

describe("triage markers", () => {
  it("is pre-approved when the triage label is on the card", () => {
    expect(isPreapproved(card("TASK-1", "proposed", { labels: ["triage-preapproved", "kind-spike"] }))).toBe(true);
    expect(isPreapproved(card("TASK-2", "proposed", { labels: ["kind-spike"] }))).toBe(false);
  });

  it("reads the reason of the last pre-approved verdict comment", () => {
    const comments = [
      { created: "", text: "triage verdict: pre-approved: first look" },
      { created: "", text: "unrelated" },
      { created: "", text: "triage verdict: pre-approved: Fits the board design; no duplicate." },
    ];
    expect(verdictOf(comments)).toBe("Fits the board design; no duplicate.");
    expect(verdictOf([{ created: "", text: "unrelated" }])).toBe("");
    expect(verdictOf(undefined)).toBe("");
  });

  it("reads kind and size from the labels", () => {
    expect(kindOf(["size-5", "kind-execute"])).toBe("execute");
    expect(sizeOf(["size-5", "kind-execute"])).toBe("5");
    expect(kindOf(["x"])).toBe("");
    expect(sizeOf([])).toBe("");
  });
});

describe("modelOf", () => {
  const harnesses = {
    tiers: ["standard"],
    harnesses: [{ name: "claude", label: "Claude", sessions: true, reason: "", tiers: { standard: { model: "sonnet", efforts: ["high"], models: { high: "claude-sonnet-5-5" } } } }],
  };
  it("names the model a profile runs", () => {
    expect(modelOf("@agent-standard-high", harnesses)).toBe("claude-sonnet-5-5");
  });
  it("is empty for a profile no harness runs and for no profile", () => {
    expect(modelOf("@agent-nope", harnesses)).toBe("");
    expect(modelOf("", harnesses)).toBe("");
  });
});

describe("matchesQuery", () => {
  const c = card("TASK-12", "proposed", { title: "Speed up CI", description: "" });
  it("matches every word against the id, title and description, case-blind", () => {
    expect(matchesQuery(c, "task-12")).toBe(true);
    expect(matchesQuery(c, "speed ci")).toBe(true);
    expect(matchesQuery(c, "flaky ci")).toBe(false);
    expect(matchesQuery(c, "  ")).toBe(true);
  });
  it("matches the description the detail loaded", () => {
    expect(matchesQuery(c, "cache", "Warm the cache.")).toBe(true);
  });
});

describe("groupsOf", () => {
  const cards = [
    card("TASK-1", "proposed", { milestone: "m-2", labels: ["kind-spike"], created: 100 }),
    card("TASK-2", "proposed", { milestone: "", labels: ["kind-execute"], created: 300 }),
    card("TASK-3", "proposed", { milestone: "m-2", labels: ["kind-execute"], created: 200 }),
  ];
  const details = { "TASK-1": { priority: "low" }, "TASK-2": { priority: "high" } };
  const ids = (groups: ReturnType<typeof groupsOf>) => groups.map((g) => [g.label, g.cards.map((x) => x.id)]);

  it("is one unlabeled group without grouping, in the chosen order", () => {
    expect(ids(groupsOf(cards, "none", "oldest", details))).toEqual([["", ["TASK-1", "TASK-3", "TASK-2"]]]);
    expect(ids(groupsOf(cards, "none", "priority", details))).toEqual([["", ["TASK-2", "TASK-1", "TASK-3"]]]);
  });

  it("groups by milestone, with the unmilestoned last", () => {
    expect(ids(groupsOf(cards, "milestone", "newest", details))).toEqual([["m-2", ["TASK-3", "TASK-1"]], ["No milestone", ["TASK-2"]]]);
  });

  it("groups by priority, high first and unknown last", () => {
    expect(ids(groupsOf(cards, "priority", "newest", details))).toEqual([["high", ["TASK-2"]], ["low", ["TASK-1"]], ["No priority", ["TASK-3"]]]);
  });

  it("groups by kind, alphabetical with no kind last", () => {
    expect(ids(groupsOf(cards, "kind", "newest", details))).toEqual([["execute", ["TASK-2", "TASK-3"]], ["spike", ["TASK-1"]]]);
  });
});
