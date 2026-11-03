import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ResumeControl } from "./ResumeControl";

const SESSION = "https://claude.ai/code/session_01";

describe("the resume control", () => {
  it("offers a Resume button and an optional reply, with no link before any resume", () => {
    const html = renderToStaticMarkup(<ResumeControl task="TASK-9" recorded={null} disabled={false} />);

    expect(html).toContain("↻ Resume");
    expect(html).toContain('aria-label="Reply for the resumed session"');
    expect(html).not.toContain("Open resumed session");
  });

  it("links the session the task recorded", () => {
    const html = renderToStaticMarkup(<ResumeControl task="TASK-9" recorded={SESSION} disabled={false} />);

    expect(html).toContain(`href="${SESSION}"`);
  });

  it("disables Resume while the task is being written", () => {
    const html = renderToStaticMarkup(<ResumeControl task="TASK-9" recorded={null} disabled />);

    expect(html).toMatch(/<button[^>]*disabled/);
  });
});
