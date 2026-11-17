// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TrackerCard } from "./ConnectTracker";

let host: HTMLDivElement, root: Root;
const writeText = vi.fn();
const draw = async () => { await act(async () => root.render(<TrackerCard />)); };
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel)!;
const all = (sel: string) => [...host.querySelectorAll<HTMLElement>(sel)];
const click = (el: Element) => act(async () => { (el as HTMLElement).click(); });
const key = (k: string) => act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); });
const open = async () => { await draw(); await click(q("button[aria-haspopup=dialog]")); };
const row = (name: string) => all(".tk-row").find((r) => r.querySelector("b")!.textContent === name)!;
const commands = (name: string) => all(".tk").find((s) => s.contains(row(name)))!.querySelectorAll("li .cmd code");

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  writeText.mockReset().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("Connect a tracker", () => {
  it("is a button on the Admin view's Tracker card until it is opened", async () => {
    await draw();

    expect(q("h2").textContent).toContain("Tracker");
    expect(host.textContent).toContain("Connect a tracker");
    expect(host.textContent).toContain("StarPulse's own Markdown board");
    expect(host.querySelector("[role=dialog]")).toBeNull();
  });

  it("lists the native board, collapsed, with its badge, and no GitHub", async () => {
    await open();

    expect(all(".tk-row b").map((b) => b.textContent)).toEqual(["StarPulse board"]);
    expect(all(".tk-row").map((r) => r.getAttribute("aria-expanded"))).toEqual(["false"]);
    expect(all(".tk-row .badge").map((b) => b.textContent)).toEqual(["connected"]);
    expect(host.querySelector("ol")).toBeNull();
    expect(host.querySelector(".cmd")).toBeNull();
    expect(host.textContent).not.toContain("GitHub");
  });

  it("expands a row to its numbered steps, the commands in order, and collapses it again", async () => {
    await open();

    await click(row("StarPulse board"));
    expect(row("StarPulse board").getAttribute("aria-expanded")).toBe("true");
    expect(q("ol").querySelectorAll(":scope > li")).toHaveLength(2);

    await click(row("StarPulse board"));
    expect(row("StarPulse board").getAttribute("aria-expanded")).toBe("false");
    expect(host.querySelector("ol")).toBeNull();
  });

  it("opens the native board at its connect command, with no output line", async () => {
    await open();
    await click(row("StarPulse board"));

    expect([...commands("StarPulse board")].map((c) => c.textContent)).toEqual(["starpulse connect native --path .starpulse/board --machine board.yaml"]);
    expect(all(".out")).toEqual([]);
    expect(all(".cmd .ps").every((p) => p.textContent === "$")).toBe(true);
  });

  it("copies the exact command with its Copy button and says so", async () => {
    await open();
    await click(row("StarPulse board"));

    const copy = q<HTMLButtonElement>('button[aria-label="Copy starpulse connect native --path .starpulse/board --machine board.yaml"]');
    await click(copy);

    expect(writeText).toHaveBeenCalledExactlyOnceWith("starpulse connect native --path .starpulse/board --machine board.yaml");
    expect(copy.textContent).toContain("Copied");
    expect(all(".tm-copy").filter((b) => b.textContent!.includes("Copied"))).toHaveLength(1);
  });

  it("closes on Esc and on a click outside the modal, not on a click inside it, and ignores other keys", async () => {
    await open();
    await click(q("[role=dialog]"));
    await key("Enter");
    expect(host.querySelector("[role=dialog]")).not.toBeNull();

    await key("Escape");
    expect(host.querySelector("[role=dialog]")).toBeNull();

    await click(q("button[aria-haspopup=dialog]"));
    await click(q("#tkm"));
    expect(host.querySelector("[role=dialog]")).toBeNull();

    await click(q("button[aria-haspopup=dialog]"));
    await click(q('button[aria-label="Close"]'));
    expect(host.querySelector("[role=dialog]")).toBeNull();
  });

  it("stops listening for Esc once closed", async () => {
    await open();
    await key("Escape");
    await key("Escape");

    expect(host.querySelector("[role=dialog]")).toBeNull();
  });
});
