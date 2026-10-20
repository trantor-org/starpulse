import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DetailsPanel, DriftBadge, OrbitCard } from "./OrbitCard";
import sheet from "../../style.css?raw";

describe("the drift badge", () => {
  it("names each drifted source with the states it gained and lost, and is nothing when none drifted", () => {
    const html = renderToStaticMarkup(<DriftBadge sources={[{ name: "codex-review", drift: { added: ["triage"], removed: ["waiting"] } }, { name: "plain" }]} />);
    expect(html).toContain("codex-review");
    expect(html).toContain("+triage");
    expect(html).toContain("−waiting");
    expect(html).not.toContain("plain");
    expect(renderToStaticMarkup(<DriftBadge sources={[{ name: "plain" }]} />)).toBe("");
  });

  it("follows the card's title and subtitle at any text size rather than sitting at a fixed offset under them", () => {
    const rule = sheet.match(/#og \.og-drift \{([^}]*)\}/)?.[1] ?? "";
    expect(rule).not.toBe("");
    expect(rule).not.toMatch(/position:\s*(absolute|fixed)|(^|[;\s])top:/);
  });
});

describe("the orbit card's states", () => {
  const card = (state: Parameters<typeof OrbitCard>[0]["state"]) => renderToStaticMarkup(<OrbitCard state={state} retry={() => {}} motion={false} />);

  it("shows the message and a retry for an error, and a reading note while it loads", () => {
    const err = card({ kind: "error", message: "no runs kept" });
    expect(err).toContain("no runs kept");
    expect(err).toContain("Retry");
    expect(card({ kind: "loading" })).toContain("Reading");
  });
});

describe("the details panel", () => {
  it("names the body, lists its facts and sections, marks an aging run in words, counts the rows past five, and offers a close", () => {
    const html = renderToStaticMarkup(<DetailsPanel close={() => {}} details={{
      kind: "source", name: "alpha", facts: [["Open now", "2"]],
      sections: [{ title: "Open runs, oldest first", rows: [{ label: "T-1", value: "REVIEW · 4d", warn: true }], more: 3 }],
    }} />);
    for (const s of ["alpha", "Open now", "Open runs, oldest first", "REVIEW · 4d · aging", "+3 more", 'aria-label="Close details"']) expect(html).toContain(s);
  });
});
