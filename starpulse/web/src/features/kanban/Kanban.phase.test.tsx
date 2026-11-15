// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import type { KanbanTask, PhaseAt } from "./kanbanModel";
import { ago } from "../../shared/clock";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const NOW = Date.now() / 1000;
const st = (id: string, final = false) => ({ id, name: id, initial: false, final });
const BUILD: PhaseAt = { chain: ["build"], state: "red_proven", at: NOW - 30, track: [st("worktree_ready"), st("red_proven"), st("green"), st("done", true)] };
const card = (id: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({
  id, title: id, lane: "in_progress", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
  live: { machine: "build", state: "red_proven", at: NOW - 30 }, phase: BUILD, ...extra,
});

let host: HTMLDivElement, root: Root;
const mount = (cards: KanbanTask[]) => {
  const hud = { cards, names: { in_progress: "In progress", review: "Review" }, roles: LIFECYCLE_ROLES, claims: {}, boardUrl: null } as unknown as HudState;
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} onQuery={() => {}} />));
};
const on = (id: string) => host.querySelector<HTMLElement>(`.card[data-id=${id}]`)!;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("a working card's phase track", () => {
  it("names its phase and step over the phase's stations, the marker at the step and the steps before it passed", () => {
    mount([card("TASK-1")]);

    const ph = on("TASK-1").querySelector(".ph")!;
    expect(ph.querySelector(".chain")!.textContent).toContain("build· red proven");
    expect(ph.querySelector(".trk.on.phase")).not.toBeNull();
    expect([...ph.querySelectorAll(".st")].map((s) => s.className)).toEqual(["st past", "st", "st", "st fin"]);
    expect(ph.querySelector<HTMLElement>(".mk")!.style.left).toMatch(/^33\.3/);
    expect(on("TASK-1").querySelector(".mach")).toBeNull();
  });

  it("ages and heats the track by its phase's step, not by a newer session in another machine", () => {
    mount([card("TASK-5", { live: { machine: "harness", state: "stopped", at: NOW }, phase: { ...BUILD, at: NOW - 3600 } })]);

    const ph = on("TASK-5").querySelector(".ph")!;
    expect(ph.querySelector(".ago")!.textContent).toBe(ago(3600));
    expect(ph.querySelector(".mk.hot")).toBeNull();
  });

  it("chains a submachine after its phase, the submachine's rail in its own colour", () => {
    mount([card("TASK-2", { live: { machine: "verify", state: "applied", at: NOW }, phase: { chain: ["deliver", "ci", "verify"], state: "applied", at: NOW, track: [st("merged"), st("applied")] } })]);

    expect([...on("TASK-2").querySelectorAll(".ph .chain b")].map((b) => b.textContent)).toEqual(["deliver", "ci", "verify"]);
    expect(on("TASK-2").querySelector(".ph .chain b.cur")!.textContent).toBe("verify");
    expect(on("TASK-2").querySelector(".ph .trk.on")!.classList.contains("phase")).toBe(false);
  });

  it("streaks the marker's glide when the step moves and tears the old rail down when the machine changes", () => {
    mount([card("TASK-3")]);
    mount([card("TASK-3", { phase: { ...BUILD, state: "green" } })]);
    expect(on("TASK-3").querySelector(".ph .sk")).not.toBeNull();

    mount([card("TASK-3", { phase: { chain: ["deliver"], state: "start", at: NOW, track: [st("start"), st("ci")] } })]);
    expect(on("TASK-3").querySelector(".ph .trk.out")).not.toBeNull();
    expect(on("TASK-3").querySelector(".ph .sk")).toBeNull();
  });

  it("keeps the machine line for a card in no phase, or outside In Progress", () => {
    mount([card("TASK-4", { phase: null }), card("TASK-5", { lane: "review" })]);

    expect(on("TASK-4").querySelector(".ph")).toBeNull();
    expect(on("TASK-4").querySelector(".mach")!.textContent).toContain("build");
    expect(on("TASK-5").querySelector(".ph")).toBeNull();
  });
});
