import { describe, expect, it } from "vitest";
import { backStep, canvasSpace, levelParams, levelSearch, retired, viewOf, viewSearch, type Back } from "./nav";
import { fitLevel, toScreen } from "../render/zoom";

describe("the canvas beside the panel", () => {
  const level = { w: 2400, h: 400, box: [0, 0, 2400, 400] as [number, number, number, number] };
  const space = canvasSpace(1920, 250, 250);

  it("spans the page between the panel and the rail", () => {
    expect(space).toEqual({ left: 250, width: 1420 });
  });

  it("fits the level in the middle of that span", () => {
    const fit = fitLevel(level, space.width, 1000);
    expect(space.left + toScreen(fit, { x: 1200, y: 200 }).x).toBe(250 + 1420 / 2);
  });
});

describe("the view in the address", () => {
  it("is the Star Map unless the address asks for the Kanban", () => {
    expect(viewOf("")).toBe("constellation");
    expect(viewOf("?demo")).toBe("constellation");
    expect(viewOf("?view=kanban")).toBe("kanban");
    expect(viewOf("?view=nonsense")).toBe("constellation");
  });

  it("opens the Admin view for ?view=admin, beside the other parameters", () => {
    expect(viewOf("?view=admin")).toBe("admin");
    expect(viewOf("?view=graph")).toBe("graph");
    expect(viewOf("?view=dags")).toBe("dags");
    expect(viewSearch("?demo&suns=working", "graph")).toBe("?demo&suns=working&view=graph");
    expect(viewOf("?demo&view=admin")).toBe("admin");
    expect(viewSearch("?demo", "admin")).toBe("?demo&view=admin");
    expect(viewSearch("?view=admin&demo", "kanban")).toBe("?demo&view=kanban");
    expect(viewSearch("?view=admin", "constellation")).toBe("");
  });

  it("is written beside the other parameters, and the Star Map leaves the address bare", () => {
    expect(viewSearch("?demo", "kanban")).toBe("?demo&view=kanban");
    expect(viewSearch("?view=kanban&demo", "constellation")).toBe("?demo");
    expect(viewSearch("?view=kanban", "constellation")).toBe("");
    expect(viewSearch("", "kanban")).toBe("?view=kanban");
  });
});

describe("the view a bare address opens", () => {
  it("opens the chosen view only when the address names none", () => {
    expect(viewOf("", "kanban")).toBe("kanban");
    expect(viewOf("?demo", "kanban")).toBe("kanban");
    expect(viewOf("?view=constellation", "kanban")).toBe("constellation");
    expect(viewOf("?view=admin", "kanban")).toBe("admin");
    expect(viewOf("?view=nonsense", "kanban")).toBe("constellation");
    expect(viewOf("")).toBe("constellation");
  });

  it("writes the view into the address unless it is the one a bare address opens", () => {
    expect(viewSearch("", "kanban", "kanban")).toBe("");
    expect(viewSearch("?demo", "kanban", "kanban")).toBe("?demo");
    expect(viewSearch("", "constellation", "kanban")).toBe("?view=constellation");
    expect(viewSearch("?view=kanban&demo", "constellation", "kanban")).toBe("?demo&view=constellation");
    expect(viewSearch("", "admin", "kanban")).toBe("?view=admin");
    expect(viewSearch("", "kanban")).toBe("?view=kanban");
  });
});

describe("a retired per-graph address", () => {
  it("is any path but the root, or any hash", () => {
    expect(retired("/", "")).toBe(false);
    expect(retired("/board", "")).toBe(true);
    expect(retired("/flow/backlog", "")).toBe(true);
    expect(retired("/", "#sec-board")).toBe(true);
  });
});

describe("stepping out with Escape, Backspace or a right-click", () => {
  it("closes the panel, drops the focused row, scrolls back to newest, steps up one machine at a time, then returns to the Board", () => {
    const seen: Back[] = [];
    let at = { panel: true, focus: "audit" as string | null, scrolled: true, depth: 4 };
    for (let step = backStep(at); step; step = backStep(at)) {
      seen.push(step);
      at = { panel: step === "panel" ? false : at.panel, focus: step === "focus" ? null : at.focus, scrolled: step === "scroll" ? false : at.scrolled, depth: step === "up" ? at.depth - 1 : at.depth };
    }
    expect(seen).toEqual(["panel", "focus", "scroll", "up", "up", "up"]);
  });

  it("does nothing on the Board, where there is nothing to step out of", () => {
    expect(backStep({ panel: false, focus: null, scrolled: false, depth: 1 })).toBeNull();
  });

  it("steps up at once when nothing is open, focused or scrolled", () => {
    expect(backStep({ panel: false, focus: null, scrolled: false, depth: 3 })).toBe("up");
  });
});

describe("the address that reproduces a machine level", () => {
  it("reads `open=` and `focus=`, each absent as null", () => {
    expect(levelParams("?view=dags&open=scan&focus=lint")).toEqual({ open: "scan", focus: "lint" });
    expect(levelParams("")).toEqual({ open: null, focus: null });
  });

  it("writes them beside the other parameters and drops each that has no value", () => {
    expect(levelSearch("?view=dags", { open: "scan", focus: "lint" })).toBe("?view=dags&open=scan&focus=lint");
    expect(levelSearch("?open=scan&focus=lint&view=dags", { open: "scan", focus: null })).toBe("?view=dags&open=scan");
    expect(levelSearch("?open=scan&focus=lint", { open: null, focus: null })).toBe("");
  });
});
