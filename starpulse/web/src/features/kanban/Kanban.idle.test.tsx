// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore, startLane } from "./start";

// every card asks startLane while it draws, so its calls count the cards a render drew
vi.mock("./start", async (actual) => {
  const start = await actual<typeof import("./start")>();
  return { ...start, startLane: vi.fn(start.startLane) };
});

const card = (id: string, title = `title ${id}`): KanbanTask => ({
  id, title, lane: "ready", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
});
const hud = { cards: [card("TASK-1"), card("TASK-2"), card("TASK-3")], names: {}, roles: LIFECYCLE_ROLES, settled: [], stats: "live · 10:00 MST", dags: ["a"], pools: [], feed: [] } as unknown as HudState;

let host: HTMLDivElement, root: Root;
const moves = new MoveStore(async () => ({ ok: true }) as never);
const starts = new StartStore((async () => ({})) as never, moves);
const noop = () => {};
const show = (h: HudState) =>
  act(() => root.render(<Kanban hud={h} moves={moves} starts={starts} compact={false} constellation={noop} searchSlot={null} outlineSlot={null} />));
const drawn = () => vi.mocked(startLane).mock.calls.length;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  show(hud);
  vi.mocked(startLane).mockClear();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("a stream event that changes no card the board shows", () => {
  it("draws no card again", () => {
    // a dags event rewrites the clock, the DAG names and the feed, which the Kanban never shows
    show({ ...hud, stats: "live · 10:01 MST", dags: ["a", "b"], feed: [{ key: "k" }] } as unknown as HudState);

    expect(drawn()).toBe(0);
  });

  it("still draws the card that changes, and only that one", () => {
    show({ ...hud, cards: [card("TASK-1", "renamed"), ...hud.cards.slice(1)] });

    expect(drawn()).toBe(1);
    expect(host.querySelector('#cols .card[data-id="TASK-1"]')?.textContent).toContain("renamed");
  });
});

describe("a working card's footer claim chip", () => {
  const MIN = 60;
  const t0 = new Date("2026-11-16T10:00:00Z").getTime() / 1000;
  const working = (assignee: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({ ...card("TASK-9"), lane: "in_progress", assignee, ...extra });
  const shown = (t: KanbanTask) => show({ ...hud, cards: [t] });
  const chip = () => host.querySelector<HTMLElement>(".card[data-id=TASK-9] .who")!;

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
    vi.setSystemTime(t0 * 1000);
    // the board read its clock when the outer setup drew it, so this block's board starts on the fixed clock
    act(() => root.unmount());
    root = createRoot(host);
  });
  afterEach(() => vi.useRealTimers());

  it("draws a held card with only its holder, however long it has been held", () => {
    shown(working("@agent-a"));
    expect(chip().textContent).toBe("a");

    act(() => void vi.advanceTimersByTime(30 * MIN * 1000));
    expect(chip().textContent).toBe("a");
  });

  it("counts a swept claim's idle time from its expiry, the session struck", () => {
    shown(working("", { release: { at: t0 - 30 * MIN, last_renewal: t0 - 45 * MIN, session: "@agent-deep", ttl: 10 * MIN } }));

    expect(chip().className).toBe("who idle");
    expect(chip().querySelector("s")!.textContent).toBe("deep");
    expect(chip().textContent).toBe("deep· idle 35m");
  });

  it("clears the idle time when a returning session claims the task", () => {
    shown(working("", { release: { at: t0 - 5 * MIN, last_renewal: t0 - 15 * MIN, session: "@agent-a", ttl: 10 * MIN } }));
    expect(chip().textContent).toBe("a· idle 5m");

    shown(working("@agent-b", { release: null }));
    expect(chip().textContent).toBe("b");
  });
});
