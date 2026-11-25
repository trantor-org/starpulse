import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Rail } from "../App";
import type { HudState } from "../render/hud";

const hud = { feed: [] } as unknown as HudState;

describe("the right rail", () => {
  it("holds only the recent events, with no legend, in every view", () => {
    const html = renderToStaticMarkup(<Rail hud={hud} />);

    expect([...html.matchAll(/<h3>([^<]+)<\/h3>/g)].map((m) => m[1])).toEqual(["Recent"]);
    expect(html).not.toContain("legend");
  });
});
