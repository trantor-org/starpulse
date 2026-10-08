// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Kanban } from "./Kanban";
import { Kept } from "../../shared/Kept";
import type { HudState } from "../../render/hud";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const hud = { cards: [], names: {}, claims: {}, boardUrl: null } as unknown as HudState;
let host: HTMLDivElement, search: HTMLDivElement, outline: HTMLDivElement, root: Root;

/** The Kanban inside the keep-alive App wraps it in, over the navigator's slots, which sit outside the view. */
const render = (on: boolean) => {
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(
    <Kept on={on}>
      <Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={search} outlineSlot={outline} onQuery={() => {}} />
    </Kept>,
  ));
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  search = document.body.appendChild(document.createElement("div"));
  outline = document.body.appendChild(document.createElement("div"));
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  for (const el of [host, search, outline]) el.remove();
});

describe("a Kanban left behind by the view switch", () => {
  it("takes its search box and outline out of the navigator, and puts them back once it is live again", async () => {
    render(true);
    expect(search.querySelector("#kbq")).not.toBeNull();

    render(false);
    expect(search.querySelector("#kbq")).toBeNull();
    expect(outline.childElementCount).toBe(0);

    render(true);
    expect(search.querySelector("#kbq")).toBeNull();
    await act(async () => { for (let i = 0; i < 3; i++) await new Promise((r) => requestAnimationFrame(r)); });
    expect(search.querySelector("#kbq")).not.toBeNull();
  });
});
