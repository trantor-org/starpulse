// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Proposals } from "./Proposals";
import { card } from "../../tests/taskViewFixtures";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";

const roles = { ...LIFECYCLE_ROLES, final: "archived", proposed: "proposed" };
const PROFILES = ["@agent-standard-high", "@agent-simple"];
const records: Record<string, object> = {
  "TASK-1": {
    title: "a", profile: "", createdBy: "claude:c4d52088",
    description: "Slow test.\n\n## Duplicate Search\n\nq\n\n## Duplicate Resolution\n\nTASK-9: distinct.",
  },
  "TASK-3": { title: "c", profile: "@agent-simple", createdBy: "", description: "Flaky." },
};

let host: HTMLElement;
let root: Root;
let calls: { url: string; body?: Record<string, unknown> }[];

const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
  const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
  calls.push({ url, body });
  if (url.startsWith("/api/task-records?ids=")) {
    const ids = decodeURIComponent(url.split("ids=")[1]).split(",");
    return { ok: true, json: async () => ({ records: ids.filter((i) => records[i]).map((i) => ({ task: i, record: records[i] })) }) } as Response;
  }
  const id = decodeURIComponent(url.split("/api/task/")[1] ?? "");
  return { ok: true, json: async () => ({ record: records[id] ?? null }) } as Response;
});

const cards = [
  card("TASK-1", "proposed", { title: "Speed up test A", created: 100 }), card("TASK-2", "ready", { title: "Ready one" }),
  card("TASK-3", "proposed", { title: "Fix flaky B", created: 300 }), card("TASK-4", "review", { title: "In review" }),
];

async function draw(list = cards) {
  await act(async () => root.render(<Proposals cards={list} roles={roles} profiles={PROFILES} fetcher={fetcher} />));
}
const button = (text: string, within: Element = host) => [...within.querySelectorAll("button")].find((b) => b.textContent === text) as HTMLButtonElement;
const row = (id: string) => host.querySelector(`[data-task="${id}"]`) as HTMLElement;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  calls = [];
  fetcher.mockClear();
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the Proposals view", () => {
  it("lists every Proposed task, newest first, and no task in another State", async () => {
    await draw();
    expect([...host.querySelectorAll("[data-task]")].map((r) => r.getAttribute("data-task"))).toEqual(["TASK-3", "TASK-1"]);
    expect(host.textContent).not.toContain("Ready one");
    expect(host.textContent).not.toContain("In review");
  });

  it("shows each proposal's title, why, filing session and duplicate resolution", async () => {
    await draw();
    const text = row("TASK-1").textContent ?? "";
    expect(text).toContain("Speed up test A");
    expect(text).toContain("Slow test.");
    expect(text).toContain("claude:c4d52088");
    expect(text).toContain("TASK-9: distinct.");
    expect(text).not.toContain("Duplicate Search");
  });

  it("reads every proposal's detail in one request, not one read per proposal", async () => {
    await draw();
    expect(calls.map((c) => c.url)).toEqual(["/api/task-records?ids=TASK-3%2CTASK-1"]);
  });

  it("says so when nothing is proposed", async () => {
    await draw([card("TASK-2", "ready")]);
    expect(host.textContent).toContain("No proposals");
  });

  it("promotes with the chosen profile: an edit of the profile, then a move to Ready", async () => {
    await draw();
    const select = row("TASK-1").querySelector("select") as HTMLSelectElement;
    await act(async () => {
      select.value = "@agent-standard-high";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => button("Promote", row("TASK-1")).click());
    const writes = calls.filter((c) => c.body);
    expect(writes.map((c) => c.url)).toEqual(["/api/edit", "/api/move"]);
    expect(writes[0].body).toMatchObject({ task: "TASK-1", changes: { profile: "@agent-standard-high" } });
    expect(writes[1].body).toMatchObject({ task: "TASK-1", to: "ready" });
  });

  it("drops a proposal with a move to the final State", async () => {
    await draw();
    await act(async () => button("Drop", row("TASK-3")).click());
    const writes = calls.filter((c) => c.body);
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({ url: "/api/move", body: { task: "TASK-3", to: "archived" } });
  });

  it("keeps a refused promotion on its row with the reason", async () => {
    fetcher.mockImplementationOnce(async () => ({ ok: true, json: async () => ({ records: [{ task: "TASK-3", record: records["TASK-3"] }] }) }) as Response);
    await draw();
    fetcher.mockImplementationOnce(async () => ({ ok: false, status: 409, json: async () => ({ error: "ready needs a profile" }) }) as Response);
    await act(async () => button("Promote", row("TASK-3")).click());
    expect(row("TASK-3").textContent).toContain("ready needs a profile");
  });
});

describe("sections, search, grouping and richer cards", () => {
  const HARNESSES = {
    tiers: ["standard"],
    harnesses: [{ name: "claude", label: "Claude", sessions: true, reason: "", tiers: { standard: { model: "sonnet", efforts: ["high"], models: { high: "claude-sonnet-5-5" } } } }],
  };
  records["TASK-5"] = {
    title: "e", profile: "@agent-standard-high", createdBy: "", description: "Cache the build.", priority: "high",
    comments: [{ created: "", text: "triage verdict: pre-approved: Fits the CI design; no duplicate." }],
  };
  records["TASK-6"] = { title: "f", profile: "", createdBy: "", description: "Rename a flag.", priority: "low", comments: [] };
  const list = [
    card("TASK-5", "proposed", { title: "Cache CI build", created: 500, labels: ["triage-preapproved", "kind-execute", "size-3"], milestone: "m-7", profile: "@agent-standard-high" }),
    card("TASK-6", "proposed", { title: "Rename flag", created: 400, labels: ["kind-spike", "size-1"], milestone: "" }),
  ];
  const drawAll = () => act(async () => root.render(<Proposals cards={list} roles={roles} profiles={PROFILES} harnesses={HARNESSES} fetcher={fetcher} />));
  const section = (name: string) => host.querySelector('[data-section="' + name + '"]') as HTMLElement;
  const type = async (label: string, value: string) => {
    const input = host.querySelector('[aria-label="' + label + '"]') as HTMLInputElement | HTMLSelectElement;
    expect(input, label + " control").not.toBeNull();
    const proto = input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    await act(async () => {
      Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(input, value);
      input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
    });
  };

  it("separates the pre-approved proposals from the unapproved with a count each", async () => {
    await drawAll();
    expect(section("preapproved").querySelector("[data-task=TASK-5]")).not.toBeNull();
    expect(section("preapproved").querySelector("[data-task=TASK-6]")).toBeNull();
    expect(section("unapproved").querySelector("[data-task=TASK-6]")).not.toBeNull();
    expect(section("preapproved").textContent).toContain("Pre-approved1");
    expect(section("unapproved").textContent).toContain("Unapproved1");
  });

  it("shows the id, profile, model, kind, size and the verdict with its reason on a pre-approved card", async () => {
    await drawAll();
    const text = row("TASK-5").textContent ?? "";
    for (const part of ["TASK-5", "@agent-standard-high", "claude-sonnet-5-5", "execute", "3", "Fits the CI design; no duplicate."]) expect(text).toContain(part);
    expect(row("TASK-6").textContent).toContain("Not triaged");
  });

  it("filters both sections by the search words", async () => {
    await drawAll();
    await type("Search proposals", "cache");
    expect(host.querySelector("[data-task=TASK-5]")).not.toBeNull();
    expect(host.querySelector("[data-task=TASK-6]")).toBeNull();
    await type("Search proposals", "task-6");
    expect(host.querySelector("[data-task=TASK-5]")).toBeNull();
    expect(host.querySelector("[data-task=TASK-6]")).not.toBeNull();
    await type("Search proposals", "nothing matches this");
    expect(host.textContent).toContain("No proposals match");
  });

  it("groups each section by milestone, priority or kind", async () => {
    await drawAll();
    await type("Group by", "kind");
    expect([...host.querySelectorAll("h3.grp .lb")].map((h) => h.textContent)).toEqual(["execute", "spike"]);
    await type("Group by", "milestone");
    expect([...host.querySelectorAll("h3.grp .lb")].map((h) => h.textContent)).toEqual(["m-7", "No milestone"]);
    await type("Group by", "priority");
    await act(async () => {});
    expect([...host.querySelectorAll("h3.grp .lb")].map((h) => h.textContent)).toEqual(["high", "low"]);
  });

  it("draws each tier as a labelled row holding a strip of its cards, priority first", async () => {
    await drawAll();
    await act(async () => {});
    const tiers = [...section("preapproved").querySelectorAll(".group")];
    expect(tiers.map((t) => t.querySelector(".lb")?.textContent)).toEqual(["high"]);
    expect([...tiers[0].querySelectorAll(".strip > .viewport-row > article.prop")].map((a) => a.getAttribute("data-task"))).toEqual(["TASK-5"]);
    expect(section("unapproved").querySelector(".strip > .viewport-row > [data-task=TASK-6]")).not.toBeNull();
  });

  it("draws the search box in the navigator's slot when it has one and filters from there", async () => {
    const slot = document.createElement("div");
    document.body.append(slot);
    await act(async () => root.render(<Proposals cards={list} roles={roles} profiles={PROFILES} harnesses={HARNESSES} searchSlot={slot} fetcher={fetcher} />));
    await act(async () => {});
    expect(host.querySelector('[aria-label="Search proposals"]:not(.mq)')).toBeNull();
    const input = slot.querySelector('[aria-label="Search proposals"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, "cache");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect([...host.querySelectorAll("article.prop")].map((a) => a.getAttribute("data-task"))).toEqual(["TASK-5"]);
    expect((host.querySelector("input.mq") as HTMLInputElement).value).toBe("cache");
    slot.remove();
  });

  it("shows the snapshot's default profile and its model when the task's own record names none", async () => {
    const defaulted = [card("TASK-6", "proposed", { title: "Rename flag", created: 400, labels: ["kind-spike"], profile: "@agent-standard-high" })];
    await act(async () => root.render(<Proposals cards={defaulted} roles={roles} profiles={PROFILES} harnesses={HARNESSES} fetcher={fetcher} />));
    await act(async () => {});
    expect(row("TASK-6").querySelector(".chip.profile")?.textContent).toBe("@agent-standard-high");
    expect(row("TASK-6").querySelector(".chip.model")?.textContent).toBe("claude-sonnet-5-5");
  });

  it("says no profile on a card that has none, with no model", async () => {
    const bare = [card("TASK-6", "proposed", { title: "Rename flag", created: 400, labels: ["kind-spike"] })];
    await act(async () => root.render(<Proposals cards={bare} roles={roles} profiles={PROFILES} harnesses={HARNESSES} fetcher={fetcher} />));
    await act(async () => {});
    expect(row("TASK-6").querySelector(".chip.profile.none")?.textContent).toBe("no profile");
    expect(row("TASK-6").querySelector(".chip.model")).toBeNull();
  });
});
