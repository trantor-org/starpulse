// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { prefetchViews } from "./lazyViews";

vi.mock("./features/kanban/Kanban", () => ({}));
vi.mock("./features/dags/Dags", () => ({}));
vi.mock("./AdminPage", () => ({}));
vi.mock("./features/level/SunsDrillIn", () => ({}));

afterEach(() => vi.restoreAllMocks());

it("lays the badge glyphs out off screen once the views prefetch, then removes the probe", () => {
  vi.stubGlobal("requestIdleCallback", (go: () => void) => (go(), 1));
  const laidOut: string[] = [];
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    laidOut.push(this.textContent ?? "");
    return new DOMRect();
  });
  prefetchViews();
  expect(laidOut.some((t) => t.includes("⌁") && t.includes("⧗") && t.includes("⛓"))).toBe(true);
  expect(document.body.children).toHaveLength(0);
});
