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
    fetcher.mockImplementationOnce(async () => ({ ok: true, json: async () => ({ record: records["TASK-3"] }) }) as Response);
    fetcher.mockImplementationOnce(async () => ({ ok: true, json: async () => ({ record: null }) }) as Response);
    await draw();
    fetcher.mockImplementationOnce(async () => ({ ok: false, status: 409, json: async () => ({ error: "ready needs a profile" }) }) as Response);
    await act(async () => button("Promote", row("TASK-3")).click());
    expect(row("TASK-3").textContent).toContain("ready needs a profile");
  });
});
