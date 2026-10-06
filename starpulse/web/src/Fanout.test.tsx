import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FeedLines, Queues } from "./Fanout";
import type { FeedLine } from "./hud";
import type { Pool } from "./types";

const pools: Pool[] = [
  { name: "dagu/deliver", cap: 32, running: 5, queued: 0 },
  { name: "dagu/models", cap: 1, running: 1, queued: 2 },
  { name: "dagu/gpu-1", cap: 1, running: 0, queued: 0 },
];

describe("the navigator's Queues section", () => {
  it("draws a row per pool with running/cap, the queued runs and a meter", () => {
    const html = renderToStaticMarkup(<Queues pools={pools} />);

    expect(html).toContain("<h3>Queues</h3>");
    expect(html).toContain("<span>deliver</span>");
    expect(html).toContain(">5/32</b>");
    expect(html).toContain(">1/1 +2</b>");
    expect(html).toContain(">0/1</b>");
    expect(html).toContain("width:15.625%");
  });

  it("colours a busy pool amber, a full one red, and leaves an idle one uncoloured", () => {
    const html = renderToStaticMarkup(<Queues pools={pools} />);

    expect(html).toContain('class="q busy"');
    expect(html).toContain('class="q full"');
    expect(html).toContain('class="q"');
    expect(html.match(/class="q full"/g)).toHaveLength(1);
  });

  it("draws no section when the adapter reports no pools", () => {
    expect(renderToStaticMarkup(<Queues pools={[]} />)).toBe("");
    expect(renderToStaticMarkup(<Queues pools={undefined} />)).toBe("");
  });
});

const line = (over: Partial<FeedLine>): FeedLine => ({ key: "k", at: 1, time: "16:00", who: "x", what: "", where: "y", ...over });

describe("the Recent feed's lines", () => {
  it("keeps the move line's shape: time, task, event, machine", () => {
    const html = renderToStaticMarkup(<FeedLines lines={[line({ who: "TASK-1", what: "moved", where: "deliver" })]} />);

    expect(html).toContain("<em>16:00</em> <b>TASK-1</b> moved <em>deliver</em>");
  });

  it("colours a run's outcome green or red and leaves the others as they are", () => {
    const html = renderToStaticMarkup(
      <FeedLines lines={[line({ key: "a", where: "succeeded · TASK-1", tone: "ok" }), line({ key: "b", where: "failed at lint · TASK-2", tone: "failed" }), line({ key: "c", where: "lint · TASK-3" })]} />,
    );

    expect(html).toContain('<em class="ok">succeeded · TASK-1</em>');
    expect(html).toContain('<em class="failed">failed at lint · TASK-2</em>');
    expect(html).toContain("<em>lint · TASK-3</em>");
  });

  it("flashes a line born after the page's first read, once", () => {
    const html = renderToStaticMarkup(<FeedLines lines={[line({ key: "a", fresh: true }), line({ key: "b" })]} />);

    expect(html.match(/class="new"/g)).toHaveLength(1);
  });
});
