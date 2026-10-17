// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StartQuestion } from "./Kanban";
import type { KanbanTask } from "./kanbanModel";
import type { Harnesses } from "./start";

const task = { id: "TASK-1", title: "Trim panels", lane: "ready", assignee: "" } as KanbanTask;
const HARNESSES: Harnesses = {
  tiers: ["fast", "standard"],
  harnesses: [{ name: "claude", label: "Claude Code", sessions: true, reason: "", tiers: { fast: { model: "haiku", efforts: [] }, standard: { model: "sonnet", efforts: ["medium", "high"] } } }],
};
const noop = () => {};
const draw = (canStart = true, harnesses = HARNESSES, desktop: (() => void) | null = null) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <StartQuestion asking={{ task, pick: { harness: "claude", tier: "standard", effort: "high" } } as never} harnesses={harnesses} names={{ ready: "Ready" }}
      canStart={canStart} pick={noop} start={noop} manual={noop} cancel={noop} desktop={desktop} />,
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

  it("adds Desktop (SSH) before Start session, with key 3, when the harness names a Desktop SSH host", () => {
    const host = draw(true, HARNESSES, noop);
    const foot = [...host.querySelectorAll(".afoot button")];
    expect(foot.map((b) => b.className)).toEqual(["cancel", "manual", "desktopbtn", "startbtn"]);
    expect(foot.map((b) => b.querySelector("kbd")!.textContent)).toEqual(["Esc", "2", "3", "1"]);
    expect(host.querySelector(".desktopbtn")!.textContent).toContain("Desktop (SSH)");
    expect(host.querySelector(".note")!.textContent).toContain("Desktop (SSH)");
  });

  it("disables only Start session when no harness can open a session", () => {
    const host = draw(false, { tiers: [], harnesses: [] });
    expect(host.querySelector<HTMLButtonElement>(".startbtn")!.disabled).toBe(true);
    expect(host.querySelector<HTMLButtonElement>(".manual")!.disabled).toBe(false);
    expect(host.querySelector(".opt > .none.wide")!.textContent).toBe("No configured harness can open a session here.");
  });
});

describe("the start question's Runs row", () => {
  it("names the model, effort and harness without repeating its label", () => {
    expect(draw().querySelector(".runs")!.textContent).toBe("sonnet at high effort on Claude Code");
  });
});
