import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ForwardingBody } from "./ForwardingCard";
import type { ForwardStatus, ForwardingView } from "./forwarding";

const STATUS: ForwardStatus = {
  configured: true, url: "https://hub.example.test/ingest", optIn: false, names: false, refused: false, lastSent: 1_700_000_000, problem: null,
  next: [
    { stream: "machine:events", fields: { machine: "board", event: "MOVED", task: "TASK-7", time: 1_700_000_100 }, kept: ["from", "session"] },
    { stream: "runs:events", fields: { phase: "start", workflow: "nightly" }, kept: [] },
  ],
  more: true,
  contract: {
    "machine:events": [{ field: "task", person: false }, { field: "actor", person: true }, { field: "assignee", person: true }],
    "runs:events": [{ field: "workflow", person: false }],
  },
};
const view = (over: Partial<ForwardingView> = {}): ForwardingView => ({ current: STATUS, phase: { kind: "idle" }, unavailable: "", ...over });
const draw = (v: ForwardingView, toggle: (on: boolean) => void = () => {}, phase?: ForwardingView["phase"]) =>
  renderToStaticMarkup(<ForwardingBody view={phase ? { ...v, phase } : v} clock="24" onToggle={toggle} />);
const withStatus = (over: Partial<ForwardStatus>) => view({ current: { ...STATUS, ...over } });

describe("the Forwarding card", () => {
  it("opted out, lists what is sent, withholds the names and keeps the switch off", () => {
    const html = draw(view());

    expect(html).toContain("hub.example.test/ingest");
    expect(html).toContain('role="switch"');
    expect(html).toContain('aria-checked="false"');
    expect(html).toContain("TASK-7");
    expect(html).toContain("MOVED");
    expect(html).toContain("Names stay on this instance");
    expect(html).toContain("+ more waiting");
  });

  it("names, per field, what is sent, what waits for the opt-in and what never leaves", () => {
    const html = draw(view());

    expect(html).toMatch(/task<\/td><td[^>]*>sent/);
    expect(html).toMatch(/actor<\/td><td[^>]*>after opt-in/);
    expect(html).toContain("Never sent");
    expect(html).toContain("session");
  });

  it("opted in, shows the names going with the batch and the switch on", () => {
    const html = draw(withStatus({ optIn: true, names: true, next: [{ stream: "machine:events", fields: { task: "TASK-7", actor: "alice" }, kept: [] }] }));

    expect(html).toContain('aria-checked="true"');
    expect(html).toContain("alice");
    expect(html).toContain("Names go with each batch");
  });

  it("says the hub refused an opt-in and that names stay home though the switch is on", () => {
    const html = draw(withStatus({ optIn: true, names: false, refused: true, problem: "hub answered 403: aggregates only" }));

    expect(html).toContain('aria-checked="true"');
    expect(html).toContain("the hub refused names");
    expect(html).toContain("Names stay on this instance");
    expect(html).toContain("<div>Names stay on this instance until the hub accepts them.</div>");
    expect(html).not.toContain("alice");
  });

  it("shows an unreachable hub with nothing sent yet, and the pending rows", () => {
    const html = draw(withStatus({ lastSent: null, problem: "hub unreachable: connection refused" }));

    expect(html).toContain("the hub did not take the last batch");
    expect(html).toContain("hub unreachable: connection refused");
    expect(html).toContain("Nothing sent since this process started");
    expect(html).toContain("TASK-7");
  });

  it("shows when the hub last took a batch", () => {
    expect(draw(view())).toMatch(/Last sent[^<]*<[^>]*>\d\d:\d\d/);
  });

  it("says an instance with no [forward] block forwards nothing, with no switch", () => {
    const html = draw(view({ current: { configured: false } }));

    expect(html).toContain("forwards nothing");
    expect(html).not.toContain('role="switch"');
  });

  it("says the status cannot be read when the server never answered", () => {
    const html = draw(view({ current: null, unavailable: "the server did not answer" }));

    expect(html).toContain("the forwarding status cannot be read");
    expect(html).toContain("the server did not answer");
    expect(html).not.toContain('role="switch"');
  });

  it("shows a refused change and disables the switch while one is saving", () => {
    expect(draw(view({ phase: { kind: "refused", reason: "forwarding takes a boolean" } }))).toContain("the server refused the change");
    expect(draw(view({ phase: { kind: "saving" } }))).toContain("disabled");
    expect(draw(view({ phase: { kind: "saved", at: 1_700_000_000 } }))).toContain("Saved");
  });

  it("does not restate what the next batch carries in a saved notice, which the hub can change afterwards", () => {
    const saved = { kind: "saved", at: 1_700_000_000 } as const;

    expect(draw(view({ phase: saved }))).not.toMatch(/carries|withholds/);
    expect(draw(withStatus({ optIn: true, names: false, refused: true, problem: "hub answered 403" }), undefined, saved)).not.toMatch(/carries|withholds/);
  });

  it("an empty queue says nothing is waiting", () => {
    expect(draw(withStatus({ next: [], more: false }))).toContain("Nothing waiting to send");
  });
});
