// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TaskView } from "./TaskView";
import { props, task } from "../../tests/taskViewFixtures";

const draw = (sessionActivity: unknown) => renderToStaticMarkup(<TaskView {...props({ task: { ...task, sessionActivity } as typeof task })} />);

describe("the holder's latest report in the task view", () => {
  it("draws the holder session's latest message with when it was written, escaped", () => {
    const at = new Date(props().now * 1000 - 300_000).toISOString();
    const html = draw({ state: "working", last_turn_at: at, last_message: "deploy <b>still</b> failing", last_message_at: at });

    expect(html).toContain("Latest report");
    expect(html).toContain("deploy &lt;b&gt;still&lt;/b&gt; failing");
    expect(html).toContain("5m ago");
  });

  it("draws no report section for a session that has not reported", () => {
    expect(draw({ state: "working", last_turn_at: "2026-11-03T20:30:00.000Z" })).not.toContain("Latest report");
    expect(renderToStaticMarkup(<TaskView {...props()} />)).not.toContain("Latest report");
  });
});
