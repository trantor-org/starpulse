import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { playLink } from "./linkDemo";

/** What the page is told, in order, as `link:<state>` and `build:<id>`. */
function told() {
  const seen: string[] = [];
  return { seen, handlers: { link: (s: string) => void seen.push(`link:${s}`), build: (id: string) => void seen.push(`build:${id}`) } };
}

describe("the connection states the demo page plays", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("holds a named state from the start, so a state can be looked at and measured", () => {
    for (const hold of ["restarting", "retrying", "offline"]) {
      const { seen, handlers } = told();
      playLink(handlers, hold, 20_000);
      expect(seen).toEqual([]); // the Board is drawn first: the note names the time of what it shows
      vi.advanceTimersByTime(60_000);
      expect(seen).toEqual([`link:${hold}`]);
    }
  });

  it("holds a loaded new build: live, then the build named", () => {
    const { seen, handlers } = told();
    playLink(handlers, "updating", 20_000);
    expect(seen).toEqual(["link:live", "build:demo-next"]);
  });

  it("plays an announced restart: live, restarting after 2 s, live again 6 s later with no new build", () => {
    const { seen, handlers } = told();
    playLink(handlers, "restart", 20_000);
    expect(seen).toEqual(["link:live"]);
    vi.advanceTimersByTime(2_000);
    expect(seen).toEqual(["link:live", "link:restarting"]);
    vi.advanceTimersByTime(6_000);
    expect(seen).toEqual(["link:live", "link:restarting", "link:live"]);
  });

  it("plays a restart that ships a new page build: the build is named once the connection is back", () => {
    const { seen, handlers } = told();
    playLink(handlers, "update", 20_000);
    vi.advanceTimersByTime(8_000);
    expect(seen).toEqual(["link:live", "link:restarting", "link:live", "build:demo-next"]);
  });

  it("plays an unannounced drop: retrying, offline once the grace ends, then back", () => {
    const { seen, handlers } = told();
    playLink(handlers, "drop", 20_000);
    vi.advanceTimersByTime(2_000);
    expect(seen).toEqual(["link:live", "link:retrying"]);
    vi.advanceTimersByTime(20_000);
    expect(seen.at(-1)).toBe("link:offline");
    vi.advanceTimersByTime(6_000);
    expect(seen.at(-1)).toBe("link:live");
  });

  it("plays nothing for an address that names no state, and stops when cancelled", () => {
    const none = told();
    playLink(none.handlers, null, 20_000);
    expect(none.seen).toEqual([]);

    const { seen, handlers } = told();
    const stop = playLink(handlers, "restart", 20_000);
    stop();
    vi.advanceTimersByTime(60_000);
    expect(seen).toEqual(["link:live"]);
  });
});
