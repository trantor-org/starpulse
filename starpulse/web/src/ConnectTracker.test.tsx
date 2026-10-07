// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectTracker } from "./ConnectTracker";

const COMMAND = "starpulse connect backlog --path backlog";
const FOUND = `Found a Backlog.md project at /work/backlog/config.yml; StarPulse is showing its own board. To show that project instead, run: ${COMMAND}`;

let host: HTMLDivElement, root: Root;
const writeText = vi.fn();
const draw = async (hint: string | null = null) => { await act(async () => root.render(<ConnectTracker hint={hint} />)); };
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel)!;
const all = (sel: string) => [...host.querySelectorAll<HTMLElement>(sel)];
const click = (el: Element) => act(async () => { (el as HTMLElement).click(); });
const key = (k: string) => act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); });
const open = async (hint: string | null = null) => { await draw(hint); await click(q("button[aria-haspopup=dialog]")); };
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
  it("is a button until it is opened", async () => {
    await draw();

    expect(host.textContent).toContain("Connect a tracker");
    expect(host.querySelector("[role=dialog]")).toBeNull();
  });

  it("lists the native board, Backlog.md and Jira, each collapsed, with its badge, and no GitHub", async () => {
    await open();

    expect(all(".tk-row b").map((b) => b.textContent)).toEqual(["StarPulse board", "Backlog.md", "Jira"]);
    expect(all(".tk-row").map((r) => r.getAttribute("aria-expanded"))).toEqual(["false", "false", "false"]);
    expect(all(".tk-row .badge").map((b) => b.textContent)).toEqual(["connected", "read-only"]);
    expect(host.querySelector("ol")).toBeNull();
    expect(host.querySelector(".cmd")).toBeNull();
    expect(host.textContent).not.toContain("GitHub");
  });

  it("expands a row to its numbered steps, the commands in order, and collapses it again", async () => {
    await open();

    await click(row("Backlog.md"));
    expect(row("Backlog.md").getAttribute("aria-expanded")).toBe("true");
    expect(row("Jira").getAttribute("aria-expanded")).toBe("false");
    expect([...commands("Backlog.md")].map((c) => c.textContent)).toEqual(["npm i -g backlog.md", COMMAND, "starpulse serve"]);
    expect(q("ol").querySelectorAll(":scope > li")).toHaveLength(3);

    await click(row("Backlog.md"));
    expect(row("Backlog.md").getAttribute("aria-expanded")).toBe("false");
    expect(host.querySelector("ol")).toBeNull();
  });

  it("opens Jira at the token export, then the connect command, then serve, and prints the summary under the connect", async () => {
    await open();
    await click(row("Jira"));

    const cmds = [...commands("Jira")].map((c) => c.textContent!);
    expect(cmds[0]).toBe("export JIRA_TOKEN=<your API token>");
    expect(cmds[1]).toMatch(/^starpulse connect jira --url https:\/\/<your-site>\.atlassian\.net --project PAY --workflow "Payments Software Workflow" --user /);
    expect(cmds[2]).toBe("starpulse serve");
    expect(all(".out").map((o) => o.textContent)).toEqual(["prints ✓ Imported Payments Software Workflow (7 states) · read 42 issues from PAY · wrote [board] to starpulse.toml"]);
    expect(all(".cmd .pr").every((p) => p.textContent === "$")).toBe(true);
  });

  it("copies the exact command with its Copy button and says so", async () => {
    await open();
    await click(row("Jira"));

    const copy = q<HTMLButtonElement>('button[aria-label="Copy export JIRA_TOKEN=<your API token>"]');
    await click(copy);

    expect(writeText).toHaveBeenCalledExactlyOnceWith("export JIRA_TOKEN=<your API token>");
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

  it("draws the found-project hint as prose over a copyable command block, only when the snapshot carries it", async () => {
    await open(FOUND);

    expect(q(".found").textContent).toContain("Found a Backlog.md project at /work/backlog/config.yml");
    expect(q(".found").textContent).not.toContain(`run: ${COMMAND}`);
    expect(q(".found .cmd code").textContent).toBe(COMMAND);
    await click(q(".found .tm-copy"));
    expect(writeText).toHaveBeenCalledExactlyOnceWith(COMMAND);
  });

  it("draws a hint with no command as prose alone, and no hint as nothing", async () => {
    await open("Found something.");
    expect(q(".found").textContent).toBe("Found something.");
    expect(host.querySelector(".found .cmd")).toBeNull();

    await key("Escape");
    for (const none of [null, ""]) {
      await draw(none);
      await click(q("button[aria-haspopup=dialog]"));
      expect(host.querySelector(".found")).toBeNull();
      await key("Escape");
    }
  });
});
