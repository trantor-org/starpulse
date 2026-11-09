import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { reloadWhenIdle, type Page } from "./reload";

/** A page the test drives: what is open, whether the tab shows, the input the user makes, and the reloads it was asked for. */
function fakePage(initial: { reloadedFor?: string | null } = {}) {
  const inputs = new Set<() => void>();
  const visible = new Set<() => void>();
  const page = {
    open: false,
    hiddenTab: false,
    reloads: 0,
    reloadedFor: initial.reloadedFor ?? null,
    input() {
      for (const fn of inputs) fn();
    },
    show(hidden: boolean) {
      page.hiddenTab = hidden;
      for (const fn of visible) fn();
    },
  };
  const api: Page = {
    now: () => Date.now(),
    busy: () => page.open,
    hidden: () => page.hiddenTab,
    onInput: (fn) => (inputs.add(fn), () => inputs.delete(fn)),
    onVisibility: (fn) => (visible.add(fn), () => visible.delete(fn)),
    reload: () => void (page.reloads += 1),
    reloaded: { get: () => page.reloadedFor, set: (build) => void (page.reloadedFor = build) },
  };
  return { page, api };
}

describe("reloading onto a new build once the page is idle", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reloads after 30 s without input, and not before", () => {
    const { page, api } = fakePage();
    reloadWhenIdle("bbb", api);

    vi.advanceTimersByTime(29_000);
    expect(page.reloads).toBe(0);
    vi.advanceTimersByTime(1_000);

    expect(page.reloads).toBe(1);
  });

  it("counts the 30 s from the last pointer, key or wheel input", () => {
    const { page, api } = fakePage();
    reloadWhenIdle("bbb", api);

    vi.advanceTimersByTime(20_000);
    page.input();
    vi.advanceTimersByTime(29_000);
    expect(page.reloads).toBe(0);
    vi.advanceTimersByTime(1_000);

    expect(page.reloads).toBe(1);
  });

  it("holds while a task view, dialog, menu or focused field is open, however long, and reloads 30 s after it closes", () => {
    const { page, api } = fakePage();
    page.open = true;
    reloadWhenIdle("bbb", api);

    vi.advanceTimersByTime(120_000);
    expect(page.reloads).toBe(0);
    page.open = false;
    page.input(); // closing it is input too
    vi.advanceTimersByTime(29_000);
    expect(page.reloads).toBe(0);
    vi.advanceTimersByTime(1_000);

    expect(page.reloads).toBe(1);
  });

  it("reloads a tab that is hidden at once, whatever is open and however recent its input", () => {
    const { page, api } = fakePage();
    page.open = true;
    reloadWhenIdle("bbb", api);
    page.input();

    page.show(true);

    expect(page.reloads).toBe(1);
  });

  it("reloads at once when the build is named to a tab that is already hidden", () => {
    const { page, api } = fakePage();
    page.hiddenTab = true;

    reloadWhenIdle("bbb", api);

    expect(page.reloads).toBe(1);
  });

  it("reloads once for a build, not again however long the page then stays idle", () => {
    const { page, api } = fakePage();
    reloadWhenIdle("bbb", api);

    vi.advanceTimersByTime(300_000);

    expect(page.reloads).toBe(1);
  });

  it("does not reload again when the build still differs after the reload it made", () => {
    const { page, api } = fakePage();
    reloadWhenIdle("bbb", api);
    vi.advanceTimersByTime(30_000);
    expect(page.reloadedFor).toBe("bbb");

    // the reloaded page is told the same build again: it asks the same, and what survived the reload says it already did
    const again = fakePage({ reloadedFor: page.reloadedFor });
    reloadWhenIdle("bbb", again.api);
    vi.advanceTimersByTime(300_000);

    expect(again.page.reloads).toBe(0);
  });

  it("reloads for a build newer than the one it last reloaded for", () => {
    const { page, api } = fakePage({ reloadedFor: "bbb" });

    reloadWhenIdle("ccc", api);
    vi.advanceTimersByTime(30_000);

    expect(page.reloads).toBe(1);
  });

  it("is cancelled by the function it returns", () => {
    const { page, api } = fakePage();

    reloadWhenIdle("bbb", api)();
    vi.advanceTimersByTime(300_000);

    expect(page.reloads).toBe(0);
  });
});
