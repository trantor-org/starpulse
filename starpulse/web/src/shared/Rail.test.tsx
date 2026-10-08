import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Rail } from "../App";
import type { HudState } from "../render/hud";

const hud = { feed: [] } as unknown as HudState;

describe("the right rail", () => {
  it.each(["graph", "kanban", "constellation"] as const)("puts the recent events at the top and the legend at the bottom in the %s view", (view) => {
    const html = renderToStaticMarkup(<Rail hud={hud} view={view} />);
    const headings = [...html.matchAll(/<h3>([^<]+)<\/h3>/g)].map((m) => m[1]);
    expect(headings[0]).toBe("Recent");
    expect(headings.at(-1)).toBe("Legend");
  });
});
