// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HudState } from "../../render/hud";
import { Kanban } from "./Kanban";
import type { KanbanTask } from "./kanban";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const card = (i: number): KanbanTask => ({
  id: `TASK-${i}`, title: `title ${i}`, lane: "ready", milestone: "m-1", labels: [], assignee: "", dependencies: [], openDeps: 0,
  prs: [], description: "", live: null, released: false, moves: {}, entered: 100 - i, created: null, workableSince: null, machines: [],
});
const cards = Array.from({ length: 40 }, (_, i) => card(i));
const hud = { cards, names: {}, claims: {}, settled: [], boardUrl: null } as unknown as HudState;

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("a long Kanban column", () => {
  it("mounts only a viewport and overscan of its cards", () => {
    const moves = new MoveStore(async () => ({ ok: true }) as never);
    act(() => root.render(
      <Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false}
        constellation={() => {}} searchSlot={null} outlineSlot={null} />,
    ));

    expect(host.querySelectorAll("#cols [data-viewport-row]")).toHaveLength(40);
    expect(host.querySelectorAll("#cols .card").length).toBeLessThan(40);
    expect(host.querySelector('[data-id="TASK-0"]')).not.toBeNull();
  });
});
