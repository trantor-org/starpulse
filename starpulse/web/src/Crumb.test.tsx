// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Crumb, crumbs } from "./Crumb";
import { BOARD, type Path } from "./levels";

const states = [{ id: "in_progress", name: "In Progress", count: 3 }, { id: "review", name: "Review", count: 1 }];
const inProgress: Path = [...BOARD, { kind: "state", id: "in_progress" }];
const machine: Path = [...inProgress, { kind: "machine", flow: "authoring-skills" }];

describe("the levels a breadcrumb lists", () => {
  it("names the Board, the state by its display name and the machine by its flow, each with the path down to it", () => {
    expect(crumbs(machine, states)).toEqual([
      { label: "Board", path: BOARD },
      { label: "In Progress", path: inProgress },
      { label: "authoring-skills", path: machine },
    ]);
  });
});

describe("a machine several Board states open", () => {
  it("is listed under the state it was opened from", () => {
    const under = (state: string): Path => [...BOARD, { kind: "state", id: state }, { kind: "machine", flow: "ci" }];
    expect(crumbs(under("review"), states).map((c) => c.label)).toEqual(["Board", "Review", "ci"]);
    expect(crumbs(under("in_progress"), states).map((c) => c.label)).toEqual(["Board", "In Progress", "ci"]);
  });
});

describe("the canvas breadcrumb", () => {
  let host: HTMLDivElement, root: Root;
  const open = vi.fn();
  const draw = (path: Path) => act(() => root.render(<Crumb path={path} states={states} open={open} />));

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    open.mockClear();
    host = document.body.appendChild(document.createElement("div"));
    root = createRoot(host);
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it("lists the drilled path with the last level marked as the current location and every level above it a button", () => {
    draw(machine);

    const nav = host.querySelector("nav#crumb")!;
    expect(nav.getAttribute("aria-label")).toBe("Where the map is drilled");
    expect([...nav.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Board", "In Progress"]);
    const here = nav.querySelectorAll("[aria-current]");
    expect(here).toHaveLength(1);
    expect(here[0].textContent).toBe("authoring-skills");
    expect(here[0].getAttribute("aria-current")).toBe("location");
    expect(here[0].tagName).not.toBe("BUTTON");
    expect([...nav.querySelectorAll(".sep")].map((s) => s.textContent)).toEqual(["›", "›"]);
  });

  it("backs the map out to the level a click names", () => {
    draw(machine);

    act(() => host.querySelector<HTMLButtonElement>("#crumb button:nth-of-type(2)")!.click());
    expect(open).toHaveBeenLastCalledWith(inProgress);
    act(() => host.querySelector<HTMLButtonElement>("#crumb button")!.click());
    expect(open).toHaveBeenLastCalledWith(BOARD);
  });

  it("is only the current Board, as plain text, before the map is drilled", () => {
    draw(BOARD);

    expect(host.querySelectorAll("#crumb button")).toHaveLength(0);
    expect(host.querySelector("#crumb [aria-current=location]")?.textContent).toBe("Board");
  });
});
