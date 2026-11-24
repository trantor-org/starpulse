import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DagLegend } from "./DagLegend";

describe("the DAGs view's legend", () => {
  it("names the dot states, the steps, an agent step, a Board tie and a runner link", () => {
    const html = renderToStaticMarkup(<DagLegend />);

    for (const word of ["running", "healthy", "last run failed", "never run", "steps", "agent step", "Board tie", "opens on its runner"]) expect(html).toContain(word);
  });
});
