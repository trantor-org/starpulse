import { describe, expect, it, vi } from "vitest";
import { canvasSpace, FoldStore, retired, viewOf, viewSearch, type FoldStorage } from "./nav";
import { fitLevel, toScreen } from "./zoom";

const memory = (): FoldStorage & { data: Map<string, string> } => {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
};
const body = { tagName: "BODY" };

describe("the navigator's fold", () => {
  it("starts open and flips with the toggle, telling its listeners", () => {
    const store = new FoldStore(memory()), seen = vi.fn();
    store.subscribe(seen);

    store.toggle();
    expect(store.get()).toBe(true);
    store.toggle();
    expect(store.get()).toBe(false);
    expect(seen).toHaveBeenCalledTimes(2);
  });

  it("flips on `[` pressed anywhere but in a text field", () => {
    const store = new FoldStore(memory());

    store.onKey({ key: "x", target: body });
    expect(store.get()).toBe(false);
    store.onKey({ key: "[", target: { tagName: "INPUT" } });
    expect(store.get()).toBe(false);
    store.onKey({ key: "[", target: body });
    expect(store.get()).toBe(true);
    store.onKey({ key: "[", target: body });
    expect(store.get()).toBe(false);
  });

  it("survives a reload: a new store on the same storage reads the last state", () => {
    const storage = memory();
    new FoldStore(storage).toggle();

    const reloaded = new FoldStore(storage);
    expect(reloaded.get()).toBe(true);
    reloaded.toggle();
    expect(new FoldStore(storage).get()).toBe(false);
  });

  it("still folds for the session when storage is off", () => {
    const off: FoldStorage = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
    const store = new FoldStore(off);

    store.toggle();
    expect(store.get()).toBe(true);
  });
});

describe("the canvas beside the panel", () => {
  const level = { w: 2400, h: 400, box: [0, 0, 2400, 400] as [number, number, number, number] };
  const space = canvasSpace(1920, { open: 250, fold: 52 }, 250);

  it("spans the page the folded panel leaves, so a fold only uncovers or covers sky", () => {
    expect(space).toEqual({ left: 52, width: 1618, inset: 198, fitWidth: 1420 });
  });

  it("fits the level between the open panel and the rail, wherever the panel is", () => {
    const fit = fitLevel(level, space.fitWidth, 1000);
    const middle = space.left + space.inset + toScreen(fit, { x: 1200, y: 200 }).x;

    expect(middle).toBe(250 + 1420 / 2);
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
