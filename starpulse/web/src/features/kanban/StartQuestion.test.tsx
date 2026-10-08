// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StartQuestion } from "./Kanban";
import type { KanbanTask } from "./kanban";
import type { Harnesses } from "./start";

const task = { id: "TASK-1", title: "Trim panels", lane: "ready", assignee: "" } as KanbanTask;
const HARNESSES: Harnesses = {
  tiers: ["fast", "standard"],
  harnesses: [{ name: "claude", label: "Claude Code", sessions: true, reason: "", tiers: { fast: { model: "haiku", efforts: [] }, standard: { model: "sonnet", efforts: ["medium", "high"] } } }],
};
const noop = () => {};
const draw = (canStart = true, harnesses = HARNESSES) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <StartQuestion asking={{ task, pick: { harness: "claude", tier: "standard", effort: "high" } } as never} harnesses={harnesses} names={{ ready: "Ready" }}
      canStart={canStart} pick={noop} start={noop} manual={noop} cancel={noop} />,
  );
  return host;
};

describe("the start question", () => {
  it("lays every pick on one label column, Runs and Assignee included", () => {
    const labels = [...draw().querySelectorAll(".opt .row > .lb")].map((e) => e.textContent);
    expect(labels).toEqual(["Tier", "Effort", "Runs", "Assignee"]);
  });

  it("puts its three answers on one footer row: Cancel, then Work it manually, then Start session, each with its key", () => {
    const foot = [...draw().querySelectorAll(".afoot button")];
    expect(foot.map((b) => b.className)).toEqual(["cancel", "manual", "startbtn"]);
    expect(foot.map((b) => b.querySelector("kbd")!.textContent)).toEqual(["Esc", "2", "1"]);
  });

  it("disables only Start session when no harness can open a session", () => {
    const host = draw(false, { tiers: [], harnesses: [] });
    expect(host.querySelector<HTMLButtonElement>(".startbtn")!.disabled).toBe(true);
    expect(host.querySelector<HTMLButtonElement>(".manual")!.disabled).toBe(false);
    expect(host.querySelector(".opt .none")!.textContent).toBe("No configured harness can open a session here.");
  });
});

describe("the start question's Runs row", () => {
  it("names the model, effort and harness without repeating its label", () => {
    expect(draw().querySelector(".runs")!.textContent).toBe("sonnet at high effort on Claude Code");
  });
});
