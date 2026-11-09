// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import { Kanban } from "./Kanban";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const LANES = { ready: "Ready", waiting: "Waiting", in_progress: "In Progress", review: "Review", needs_attention: "Needs attention", done: "Done" };
const TYPES = { ready: "initial", waiting: null, in_progress: "resting", review: "waiting_on_fact", needs_attention: "waiting_on_person", done: "final" };
const board = () => ({ cards: [], names: LANES, types: TYPES, roles: LIFECYCLE_ROLES, claims: {}, settled: [], boardUrl: null }) as unknown as HudState;

let host: HTMLDivElement, root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = () => {};
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  const moves = new MoveStore((async () => ({ ok: true })) as never);
  act(() => root.render(
    <Kanban hud={board()} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false}
      constellation={() => {}} searchSlot={null} outlineSlot={null} />,
  ));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("a column header's type glyph", () => {
  it.each([["#cols section", "desktop header"], ["#kb .lanes button", "phone lane tab"]])("draws the declared type in the %s", (site) => {
    const sel = (lane: string) => host.querySelector<SVGElement>(`${site}[data-lane=${lane}] svg.rg`);
    expect(sel("in_progress")?.dataset.type).toBe("resting");
    expect(sel("in_progress")?.getAttribute("aria-label")).toBe("Type: resting");
    expect(sel("needs_attention")?.getAttribute("aria-label")).toBe("Type: waiting on a person");
  });

  it.each([["#cols section"], ["#kb .lanes button"]])("marks a state that declares no type in the %s", (site) => {
    const mark = host.querySelector<SVGElement>(`${site}[data-lane=waiting] svg.rg`);
    expect(mark?.dataset.type).toBe("none");
    expect(mark?.getAttribute("aria-label")).toBe("No declared type");
  });

  it("names the type on hover", () => {
    expect(host.querySelector(`#cols section[data-lane=ready] svg.rg title`)?.textContent).toBe("Type: initial");
  });
});
