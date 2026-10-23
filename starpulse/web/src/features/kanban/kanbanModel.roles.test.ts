// The Kanban model over a Board whose States are renamed: the snapshot's roles say which State is which.
import { describe, expect, it } from "vitest";
import type { Snapshot } from "../../api";
import { merge } from "../../render/sky";
import { kanbanTasks } from "./kanbanModel";
import { RENAMED_NAMES, RENAMED_ROLES } from "./rolesFixtures";

const machine = { states: Object.entries(RENAMED_NAMES).map(([id, name]) => ({ id, name })), transitions: [] } as never;
const snapshot = (agents: { id: string; state: string; previous?: string }[]): Snapshot => ({
  graphs: ["board"], dags: [], flows: [{ name: "board", machine, agents: agents.map((a) => ({ title: a.id, model: "", ...a })) }],
  pulls: {}, settled: {}, error: null, now: 600, roles: RENAMED_ROLES,
}) as unknown as Snapshot;

describe("the cards drawn from a snapshot with renamed States", () => {
  it("carry the snapshot's roles onto the sky", () => {
    expect(merge(snapshot([])).roles).toEqual(RENAMED_ROLES);
  });

  it("mark a card released when it moved from the waiting State to the ready State", () => {
    const cards = kanbanTasks(merge(snapshot([
      { id: "T-1", state: "todo", previous: "parked" }, { id: "T-2", state: "todo", previous: "inbox" }, { id: "T-3", state: "parked", previous: "todo" },
    ])));

    expect(cards.map((c) => [c.id, c.released])).toEqual([["T-1", true], ["T-2", false], ["T-3", false]]);
  });

  it("leave the finished State's cards off the open set a card's dependencies count", () => {
    const cards = kanbanTasks(merge(snapshot([
      { id: "T-1", state: "shipped" }, { id: "T-2", state: "doing", dependencies: ["T-1"] } as never,
    ])));

    expect(cards.find((c) => c.id === "T-2")!.openDeps).toBe(0);
  });
});
