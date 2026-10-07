import type { ReactElement } from "react";
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

describe("a Recent line that points at a task or DAG", () => {
  const a = line({ key: "a", who: "TASK-1", task: "TASK-1" }), b = line({ key: "b", who: "dagu/nightly", dag: "dagu/nightly" });
  const rows = (props: Parameters<typeof FeedLines>[0]) => (FeedLines(props) as ReactElement<{ children: ReactElement<Record<string, () => void>>[] }>).props.children;

  it("reports hover, leave and click for a line the view can light, and leaves the others inert", () => {
    const seen: string[] = [];
    const [ra, rb] = rows({ lines: [a, b], can: (l) => !!l.task, spot: (l) => seen.push(`spot ${l?.key ?? "none"}`), pick: (l) => seen.push(`pick ${l.key}`) });

    ra.props.onPointerEnter();
    ra.props.onPointerLeave();
    ra.props.onClick();

    expect(seen).toEqual(["spot a", "spot none", "pick a"]);
    expect(rb.props.onPointerEnter).toBeUndefined();
    expect(rb.props.onClick).toBeUndefined();
  });

  it("marks only the lines the view can light as ones to point at", () => {
    const html = renderToStaticMarkup(<FeedLines lines={[a, b]} can={(l) => !!l.task} spot={() => {}} pick={() => {}} />);

    expect(html.match(/class="go"/g)).toHaveLength(1);
  });

  it("says on the hovered line why its card is not shown", () => {
    const html = renderToStaticMarkup(<FeedLines lines={[a, b]} can={() => true} spot={() => {}} pick={() => {}} note={{ key: "a", text: "hidden by the filter" }} />);

    expect(html).toContain('<span class="why">hidden by the filter</span>');
    expect(html.match(/class="why"/g)).toHaveLength(1);
  });
});
