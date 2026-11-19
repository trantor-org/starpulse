import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Rail } from "../App";
import type { HudState } from "../render/hud";

const hud = { feed: [] } as unknown as HudState;

describe("the right rail", () => {
  it.each(["kanban", "constellation"] as const)("puts the recent events at the top and the legend at the bottom in the %s view", (view) => {
    const html = renderToStaticMarkup(<Rail hud={hud} view={view} />);
    const headings = [...html.matchAll(/<h3>([^<]+)<\/h3>/g)].map((m) => m[1]);
    expect(headings[0]).toBe("Recent");
    expect(headings.at(-1)).toBe("Legend");
  });

  it("draws the closed PR pip in the kanban legend as the pip draws it: faint dot, struck-through, dimmed", () => {
    const html = renderToStaticMarkup(<Rail hud={hud} view="kanban" />);
    expect(html).toMatch(/<span[^>]*line-through[^>]*opacity:0\.75[^>]*><i style="background:var\(--faint\)"><\/i>closed<\/span>/);
  });
});
