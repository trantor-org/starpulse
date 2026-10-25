// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const NOW = Date.now() / 1000;
const card = (id: string, lane: string, assignee: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({
  id, title: id, lane, milestone: "", labels: [], assignee, dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [], ...extra,
});
const expired = { at: NOW - 45 * 60, last_renewal: NOW - 40 * 60, session: "@agent-deep", ttl: 1800 };

let host: HTMLDivElement, root: Root;
const mount = (cards: KanbanTask[]) => {
  const hud = { cards, names: {}, roles: LIFECYCLE_ROLES, claims: {}, boardUrl: null } as unknown as HudState;
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} onQuery={() => {}} />));
};
const toggle = () => host.querySelector<HTMLButtonElement>("section[data-lane=in_progress] h2 button[aria-pressed]");
const ids = () => [...host.querySelectorAll<HTMLElement>("section[data-lane=in_progress] .card")].map((c) => c.dataset.id);
const chip = (id: string) => host.querySelector<HTMLElement>(`.card[data-id=${id}] .who`)?.textContent;

const lane = [
  card("TASK-1", "in_progress", "@agent-a", { claimExpiresAt: NOW + 4 * 60 - 5 }),
  card("TASK-2", "in_progress", "", { release: expired }),
  card("TASK-3", "in_progress", ""),
  card("TASK-4", "in_progress", "@agent-b", { claimExpiresAt: NOW + 3600 }),
  card("TASK-5", "ready", "", { release: expired }),
];

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the In Progress lane's unheld toggle", () => {
  it("counts the unheld cards, filters to them on a click and restores all on a second", () => {
    mount(lane);

    expect(toggle()!.textContent).toBe("2 unheld");
    expect(toggle()!.getAttribute("aria-pressed")).toBe("false");
    expect(ids().sort()).toEqual(["TASK-1", "TASK-2", "TASK-3", "TASK-4"]);

    act(() => toggle()!.click());
    expect(toggle()!.getAttribute("aria-pressed")).toBe("true");
    expect(ids().sort()).toEqual(["TASK-2", "TASK-3"]);

    act(() => toggle()!.click());
    expect(toggle()!.getAttribute("aria-pressed")).toBe("false");
    expect(ids()).toHaveLength(4);
  });

  it("draws no toggle when every card is held, and clears itself when the last unheld task is claimed", () => {
    mount(lane);
    act(() => toggle()!.click());

    mount(lane.map((t) => (t.id === "TASK-2" || t.id === "TASK-3" ? { ...t, assignee: "@agent-c" } : t)));
    expect(toggle()).toBeNull();
    expect(ids()).toHaveLength(4);

    mount(lane);
    expect(toggle()!.getAttribute("aria-pressed")).toBe("false");
  });

  it("composes with the milestone filter", () => {
    history.replaceState(null, "", "/?milestone=m-1");
    mount(lane.map((t) => (t.id === "TASK-3" ? { ...t, milestone: "m-1" } : t)));

    expect(toggle()!.textContent).toBe("1 unheld");
    act(() => toggle()!.click());
    expect(ids()).toEqual(["TASK-3"]);
  });
});

describe("the In Progress card's footer chip", () => {
  it("strikes an expired session and ages it from the release", () => {
    mount(lane);

    expect(host.querySelector(".card[data-id=TASK-2] .who s")?.textContent).toBe("deep");
    expect(chip("TASK-2")).toBe("deep· expired 45m");
  });

  it("appends the minutes left to a held card under ten minutes from expiry", () => {
    mount(lane);

    expect(chip("TASK-1")).toBe("a· 4m left");
    expect(chip("TASK-4")).toBe("b");
  });

  it("draws a held card 20 minutes from expiry, and one outside the working lane, with neither expired nor left", () => {
    mount([
      card("TASK-6", "in_progress", "@agent-c", { claimExpiresAt: NOW + 20 * 60 }),
      card("TASK-7", "ready", "@agent-a", { claimExpiresAt: NOW + 2 * 60, release: expired }),
    ]);

    expect(chip("TASK-6")).toBe("c");
    expect(chip("TASK-7")).toBe("a");
    expect(host.textContent).not.toMatch(/expired|left|released/);
  });

  it("draws an unheld card with no release record, and a card outside the working lane, as before", () => {
    mount(lane);

    expect(chip("TASK-3")).toBe("unassigned");
    expect(chip("TASK-5")).toBe("unassigned");
  });
});
