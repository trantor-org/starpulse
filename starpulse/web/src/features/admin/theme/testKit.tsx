// Shared jsdom helpers for the Theme card's tests: a mounted tree, typing into a controlled field, and a fake server.
import type { ThemePrefs } from "./themeStore";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";

/** A fake server for the Theme card's tests: `puts` holds each body written to /api/admin, in order. */
export const server = () => {
  const puts: { theme?: unknown }[] = [];
  const fetcher = (async (_url: string, init?: { method?: string; body?: string }) => {
    if (init?.method === "PUT") puts.push(JSON.parse(init.body!));
    return new Response("{}");
  }) as never;
  return { fetcher, puts };
};
/** The theme the last write kept. */
export const saved = (s: ReturnType<typeof server>) => (s.puts.at(-1)?.theme ?? null) as ThemePrefs;

export function mount(ui: ReactNode) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.body.appendChild(document.createElement("div"));
  const root: Root = createRoot(host);
  act(() => root.render(ui));
  return { host, unmount: () => { act(() => root.unmount()); host.remove(); } };
}

/** Sets a controlled field's value the way typing does, so React sees the input event. */
export function type(el: Element, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  act(() => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

export const click = (el: Element) => act(() => (el as HTMLElement).click());
export const key = (el: Element, k: string) => act(() => void el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true })));

/** The one element matching `sel`, or a failure naming it. */
export function get<T extends Element = HTMLElement>(sel: string, within: ParentNode = document): T {
  const el = within.querySelector<T>(sel);
  if (!el) throw new Error(`no element matches ${sel}`);
  return el;
}

/** The button whose text is exactly `text`. */
export function button(text: string, within: ParentNode = document): HTMLButtonElement {
  const el = [...within.querySelectorAll("button")].find((b) => b.textContent?.trim() === text);
  if (!el) throw new Error(`no button reads ${text}`);
  return el;
}
