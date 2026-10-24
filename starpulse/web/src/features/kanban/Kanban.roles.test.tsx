// @vitest-environment jsdom
// The page over a Board whose States are renamed (todo, doing, on_me, shipped): it draws and gates by the roles the snapshot carries.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HudState } from "../../render/hud";
import { Kanban } from "./Kanban";
import { MoveStore } from "./move";
import { StartStore } from "./start";
import { RENAMED_NAMES, RENAMED_ROLES, card } from "./rolesFixtures";

const board = (cards: ReturnType<typeof card>[]) =>
  ({ cards, names: RENAMED_NAMES, roles: RENAMED_ROLES, claims: {}, settled: [], boardUrl: null }) as unknown as HudState;

let host: HTMLDivElement, root: Root;
const show = (hud: HudState) => {
  const moves = new MoveStore((async () => ({ ok: true })) as never);
  act(() => root.render(
    <Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false}
      constellation={() => {}} searchSlot={null} outlineSlot={null} />,
  ));
};
const tabs = () => [...host.querySelectorAll<HTMLElement>("#kb .lanes [role=tab]")];

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = () => {};
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("the Kanban page over renamed States", () => {
  const go = { doing: { allowed: true, reason: "", skill: "" } };
  const cards = [
    card("T-1", "todo", { moves: go }), card("T-2", "parked", { moves: go }), card("T-3", "doing"), card("T-4", "checking", { moves: go }),
    card("T-5", "on_me", { moves: go }), card("T-6", "shipped", { entered: 0 }), card("T-7", "shipped", { entered: 100 }),
  ];

  it("draws one column per role State in lifecycle order, each tagged with its role, and leaves the creation and final States off", () => {
    show(board(cards));

    expect(tabs().map((t) => [t.dataset.lane, t.dataset.role, t.querySelector(".c")?.textContent])).toEqual([
      ["todo", "ready", "1"], ["parked", "waiting", "1"], ["doing", "working", "1"], ["checking", "review", "1"], ["on_me", "attention", "1"], ["shipped", "done", "1"],
    ]);
  });

  it("opens on the working column", () => {
    show(board(cards));

    expect(host.querySelector<HTMLElement>("#cols .col.on")?.dataset.lane).toBe("doing");
  });

  it("draws a roles change again, so a session start the new roles drop goes", () => {
    const enabled = () => [...host.querySelectorAll<HTMLButtonElement>("button.play")].filter((b) => !b.disabled).map((b) => b.getAttribute("aria-label")).sort();
    const hud = board(cards), moves = new MoveStore((async () => ({ ok: true })) as never), starts = new StartStore((async () => ({})) as never, moves), constellation = () => {};
    const draw = (h: HudState) => act(() => root.render(
      <Kanban hud={h} moves={moves} starts={starts} compact={false} constellation={constellation} searchSlot={null} outlineSlot={null} />,
    ));
    draw(hud);
    expect(enabled()).toEqual(["Start T-1", "Start T-2", "Start T-5"]);

    draw({ ...hud, roles: { ...RENAMED_ROLES, startable: ["on_me", "todo"] } });

    expect(enabled()).toEqual(["Start T-1", "Start T-5"]);
  });

  it("offers a session start on the States the roles make startable, and on no other", () => {
    show(board(cards));

    const starts = [...host.querySelectorAll<HTMLButtonElement>("button.play")].map((b) => [b.getAttribute("aria-label"), b.disabled]);

    expect(starts.sort()).toEqual([["Start T-1", false], ["Start T-2", false], ["Start T-5", false]]);
  });
});
