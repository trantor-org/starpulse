import { describe, expect, it } from "vitest";
import { fetchRecord, menuKey, type MenuState } from "./taskView";

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
