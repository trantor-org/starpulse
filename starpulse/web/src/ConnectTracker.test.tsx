import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConnectTracker, TrackerPanel } from "./ConnectTracker";

const FOUND = "Found a Backlog.md project at /work/backlog/config.yml; StarPulse is showing its own board. To show that project instead, add [board] type = \"upstream_backlog\" to your starpulse.toml.";

describe("Connect a tracker", () => {
  it("is a button until it is opened", () => {
    const html = renderToStaticMarkup(<ConnectTracker hint={null} />);

    expect(html).toContain("Connect a tracker");
    expect(html).not.toContain("upstream_backlog");
  });

  it("shows the [board] configuration of Backlog.md, the public adapter", () => {
    const html = renderToStaticMarkup(<TrackerPanel hint={null} close={() => {}} />);

    expect(html).toContain("Backlog.md");
    expect(html).toContain("[board]");
    expect(html).toContain("type = &quot;upstream_backlog&quot;");
    expect(html).toContain("starpulse.toml");
  });

  it("shows the found-project hint only when the snapshot carries it", () => {
    expect(renderToStaticMarkup(<TrackerPanel hint={FOUND} close={() => {}} />)).toContain("Found a Backlog.md project at /work/backlog/config.yml");
    for (const none of [null, undefined, ""]) expect(renderToStaticMarkup(<TrackerPanel hint={none} close={() => {}} />)).not.toContain("Found a Backlog.md project");
  });
});
