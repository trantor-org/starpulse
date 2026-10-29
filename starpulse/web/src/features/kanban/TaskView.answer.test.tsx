// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskView } from "./TaskView";
import { props, task, stubWrites } from "../../tests/taskViewFixtures";

const asking = { ...task, lane: "needs_attention" };

describe("the Answer section of the task view", () => {
  const mounted: { root: ReturnType<typeof createRoot>; host: HTMLElement }[] = [];
  const mount = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => {
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    act(() => root.render(<TaskView {...props({ task: asking, ...over })} />));
    mounted.push({ root, host });
    return host;
  };
  afterEach(() => {
    for (const { root, host } of mounted.splice(0)) { act(() => root.unmount()); host.remove(); }
    vi.unstubAllGlobals();
  });
  const stubWriter = (answer: (body: Record<string, unknown>) => Response = (b) => new Response(JSON.stringify({ task: b.task, id: "a1b2c3d4e5f6" }))) => {
    const fetcher = vi.fn<typeof fetch>(async (_url, init) => answer(JSON.parse(String(init?.body))));
    stubWrites(fetcher);
    return () => fetcher.mock.calls.map(([url, init]) => ({ url: String(url), ...JSON.parse(String(init?.body)) }));
  };
  const section = (host: HTMLElement) => [...host.querySelectorAll<HTMLElement>(".tvrail .sec.rs")].find((s) => s.querySelector(".t")?.textContent === "Answer") ?? null;
  const field = (host: HTMLElement) => section(host)?.querySelector<HTMLTextAreaElement>("textarea") ?? null;
  const send = (host: HTMLElement) => section(host)?.querySelector<HTMLButtonElement>("button") ?? null;
  const type = (el: HTMLTextAreaElement | null, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    act(() => { setter.call(el, value); el!.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const click = async (el: Element | null) => { expect(el, "element to click").toBeTruthy(); await act(async () => (el as HTMLElement).click()); };

  it("draws an answer form on a task in Needs attention and on no other", () => {
    expect(field(mount())).not.toBeNull();
    expect(section(mount({ task }))).toBeNull();
  });

  it("sends the answer to /api/answer naming the task and the answer, no actor, and clears the field", async () => {
    const calls = stubWriter();
    const host = mount();

    type(field(host), "use unraid");
    await click(send(host));

    expect(calls()).toEqual([{ url: "/api/answer", task: asking.id, answer: "use unraid" }]);
    expect(field(host)?.value).toBe("");
    expect(section(host)?.querySelector(".ratemeta")?.textContent).toContain("Answered");
  });

  it("keeps the draft and says so when the answer is refused", async () => {
    stubWriter(() => new Response(JSON.stringify({ error: "An answer is the operator's" }), { status: 403 }));
    const host = mount();

    type(field(host), "use unraid");
    await click(send(host));

    expect(field(host)?.value).toBe("use unraid");
    expect(section(host)?.querySelector(".editrefusal")?.textContent).toContain("An answer is the operator's");
  });

  it("will not send a blank answer", () => {
    const host = mount();

    type(field(host), "   ");

    expect(send(host)?.disabled).toBe(true);
  });
});
