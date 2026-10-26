// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskView } from "./TaskView";
import { props, task } from "../../tests/taskViewFixtures";
import type { Rating } from "../../api";

/** The deviated sample: a step-down trial carries a `trial-` label, and only it is rated. */
const trialTask = { ...task, profile: "@agent-standard-medium", labels: [...task.labels, "trial-decide-5"] };
const rated = (over: Partial<Rating> = {}): Rating => ({ verdict: "pass", reason: "", at: 760, actor: "operator", changes: 2, ...over });

describe("the Rating section of the task view", () => {
  const mounted: { root: ReturnType<typeof createRoot>; host: HTMLElement }[] = [];
  const mount = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => {
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    act(() => root.render(<TaskView {...props({ task: trialTask, ...over })} />));
    mounted.push({ root, host });
    return host;
  };
  afterEach(() => {
    for (const { root, host } of mounted.splice(0)) { act(() => root.unmount()); host.remove(); }
    vi.unstubAllGlobals();
  });
  /** Stub the writer: `answer` makes each POST's response, the calls come back as parsed bodies. */
  const stubWriter = (answer: (body: Record<string, unknown>) => Response = (b) => new Response(JSON.stringify({ task: b.task, verdict: b.verdict, reason: b.reason ?? "", changes: 3 }))) => {
    const fetcher = vi.fn<typeof fetch>(async (_url, init) => answer(JSON.parse(String(init?.body))));
    vi.stubGlobal("fetch", fetcher);
    return () => fetcher.mock.calls.map(([url, init]) => ({ url: String(url), ...JSON.parse(String(init?.body)) }));
  };
  const section = (host: HTMLElement) => [...host.querySelectorAll<HTMLElement>(".tvrail .sec.rs")].find((s) => s.querySelector(".t")?.textContent === "Rating") ?? null;
  const button = (host: HTMLElement, verdict: string) => section(host)?.querySelector<HTMLButtonElement>(`button.ratebtn[data-verdict="${verdict}"]`) ?? null;
  const reasonField = (host: HTMLElement) => section(host)?.querySelector<HTMLInputElement>("input") ?? null;
  const click = async (el: Element | null) => { expect(el, "element to click").toBeTruthy(); await act(async () => (el as HTMLElement).click()); };
  const type = (el: HTMLInputElement | null, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { setter.call(el, value); el!.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const press = (el: Element | null, key: string) => act(() => { el!.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })); });

  it("draws no Rating row on a task without a trial- label", () => {
    const host = mount({ task });

    expect(section(host)).toBeNull();
    expect([...host.querySelectorAll(".tvrail .sec.rs .t")].map((t) => t.textContent)).not.toContain("Rating");
  });

  it("draws the Rating row on a trial- task: what was sampled, the profile it drew, then unrated Pass and Fail and no meta line", () => {
    const host = mount();

    const titles = [...host.querySelectorAll(".tvrail .sec.rs .t")].map((t) => t.textContent);
    expect(titles.slice(0, 3)).toEqual(["Status", "Rating", "Session"]);
    expect(section(host)?.querySelector(".why")?.textContent).toContain("decide work at size 5");
    expect(section(host)?.querySelector(".who2.dev")?.textContent).toContain("@agent-standard-medium");
    expect([button(host, "pass")?.getAttribute("aria-pressed"), button(host, "fail")?.getAttribute("aria-pressed")]).toEqual(["false", "false"]);
    expect(section(host)?.querySelector(".ratemeta")).toBeNull();
    expect(section(host)?.querySelector(".editrefusal")).toBeNull();
  });

  it("shows a pass with who set it, when and how many changes, the history in the meta line's title", () => {
    const host = mount({ task: { ...trialTask, rating: rated() } });

    expect(button(host, "pass")?.getAttribute("aria-pressed")).toBe("true");
    expect(button(host, "fail")?.getAttribute("aria-pressed")).toBe("false");
    const meta = section(host)?.querySelector<HTMLElement>(".ratemeta");
    expect(meta?.textContent).toBe("Passed by operator · 4m ago · 2 changes");
    expect(meta?.title).toContain("2 changes");
  });

  it("shows a fail with its saved reason and an edit button, or an add-a-reason link when it has none", () => {
    const withReason = mount({ task: { ...trialTask, rating: rated({ verdict: "fail", reason: "drops the lane filter", changes: 1 }) } });
    expect(button(withReason, "fail")?.getAttribute("aria-pressed")).toBe("true");
    expect(section(withReason)?.querySelector(".ratewhy")?.textContent).toContain("drops the lane filter");
    expect(section(withReason)?.querySelector(".ratewhy button")?.textContent).toBe("Edit");
    expect(section(withReason)?.querySelector(".ratemeta")?.textContent).toBe("Failed by operator · 4m ago · 1 change");

    const bare = mount({ task: { ...trialTask, rating: rated({ verdict: "fail", changes: 1 }) } });
    expect(section(bare)?.querySelector(".ratewhy button")?.textContent).toBe("Add a reason");
  });

  it("treats a cleared rating as none", () => {
    const host = mount({ task: { ...trialTask, rating: rated({ verdict: "cleared" }) } });

    expect([button(host, "pass")?.getAttribute("aria-pressed"), button(host, "fail")?.getAttribute("aria-pressed")]).toEqual(["false", "false"]);
    expect(section(host)?.querySelector(".ratemeta")).toBeNull();
  });

  it("posts the verdict as the operator and presses it, then clears it when the active verdict is clicked again", async () => {
    const calls = stubWriter();
    const host = mount();

    await click(button(host, "pass"));
    expect(calls()).toEqual([{ url: "/api/rating", task: "TASK-9", verdict: "pass", actor: "operator" }]);
    expect(button(host, "pass")?.getAttribute("aria-pressed")).toBe("true");
    expect(section(host)?.querySelector(".ratemeta")?.textContent).toMatch(/^Passed by operator · now · 3 changes$/);

    await click(button(host, "pass"));
    expect(calls()[1]).toMatchObject({ verdict: "cleared" });
    expect(button(host, "pass")?.getAttribute("aria-pressed")).toBe("false");
  });

  it("asks for a reason on Fail, saves it on Enter and shows it with an edit button", async () => {
    const calls = stubWriter();
    const host = mount();

    await click(button(host, "fail"));
    const field = reasonField(host);
    expect(field?.maxLength).toBe(120);
    expect(section(host)?.querySelector(".count")?.textContent).toBe("0/120");
    type(field, "drops the lane filter");
    expect(section(host)?.querySelector(".count")?.textContent).toBe("21/120");
    await act(async () => { press(field, "Enter"); });

    expect(calls().at(-1)).toMatchObject({ verdict: "fail", reason: "drops the lane filter", actor: "operator" });
    expect(reasonField(host)).toBeNull();
    expect(section(host)?.querySelector(".ratewhy")?.textContent).toContain("drops the lane filter");
    expect(section(host)?.querySelector(".ratewhy button")?.textContent).toBe("Edit");
  });

  it("closes only the reason field on Escape and leaves the modal open", async () => {
    const calls = stubWriter();
    const close = vi.fn();
    const host = mount({ close });

    await click(button(host, "fail"));
    expect(reasonField(host)).toBeTruthy();
    const before = calls().length;
    press(reasonField(host), "Escape");

    expect(reasonField(host)).toBeNull();
    expect(close).not.toHaveBeenCalled();
    expect(calls()).toHaveLength(before);
    expect(section(host)?.querySelector(".ratewhy button")?.textContent).toBe("Add a reason");
  });

  it("still closes the modal on Escape anywhere else", () => {
    const close = vi.fn();
    mount({ close });

    act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });

    expect(close).toHaveBeenCalledTimes(1);
  });

  it("shows saving and holds both buttons while the write runs", async () => {
    let release: (r: Response) => void = () => {};
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => new Promise<Response>((resolve) => { release = resolve; })));
    const host = mount();

    await click(button(host, "pass"));
    expect(section(host)?.textContent).toContain("saving");
    expect([button(host, "pass")?.disabled, button(host, "fail")?.disabled]).toEqual([true, true]);

    await act(async () => release(new Response(JSON.stringify({ task: "TASK-9", verdict: "pass", reason: "", changes: 1 }))));
    expect(section(host)?.textContent).not.toContain("saving");
  });

  it("answers a refused write with the Rating not saved line and keeps the rating it had", async () => {
    stubWriter(() => new Response(JSON.stringify({ error: "rating not saved" }), { status: 503 }));
    const host = mount({ task: { ...trialTask, rating: rated() } });

    await click(button(host, "fail"));

    expect(section(host)?.querySelector(".editrefusal")?.textContent).toBe("Rating not saved.");
    expect(button(host, "pass")?.getAttribute("aria-pressed")).toBe("true");
    expect(button(host, "fail")?.getAttribute("aria-pressed")).toBe("false");
  });
});
