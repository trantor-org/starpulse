// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const page = readFileSync(new URL("../../index.html", import.meta.url), "utf8");

/** Every `<link>` tag in the page's head, as its attributes. */
function links(): Record<string, string>[] {
  return [...page.matchAll(/<link\b([^>]*)>/g)].map(([, attrs]) =>
    Object.fromEntries([...attrs.matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(([, k, v]) => [k, v ?? ""])),
  );
}

describe("index.html's first paint", () => {
  it("waits on no stylesheet from another origin: a pending one holds the bundle's script until it arrives", () => {
    const blocking = links().filter((l) => l.rel === "stylesheet" && /^https?:/.test(l.href ?? "") && l.media !== "print");
    expect(blocking).toEqual([]);
  });

  it("links no font host: the page serves its own fonts, so no load paints in a fallback face or waits on another origin", () => {
    expect(page).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
  });

  it("preloads, from its own origin, each face the first frame draws", () => {
    const preloaded = links().filter((l) => l.rel === "preload" && l.as === "font");
    for (const l of preloaded) {
      expect(l.type).toBe("font/woff2");
      expect(l).toHaveProperty("crossorigin"); // a font fetch is anonymous-CORS, so a preload without it is fetched twice
      expect(l.href).not.toMatch(/^(https?:)?\/\//);
    }
    expect(preloaded.map((l) => l.href?.split("/").pop()?.replace(/\.woff2$/, "")).sort()).toEqual([
      "inter-latin-300-normal",
      "inter-latin-400-normal",
      "inter-latin-500-normal",
      "jetbrains-mono-latin-400-normal",
    ]);
  });
});

describe("index.html's early stream", () => {
  const inline = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(([, body]) => body);
  const streamSource = readFileSync(new URL("../api/stream.ts", import.meta.url), "utf8");

  class Source {
    listeners = new Map<string, ((e: { type: string; data: string }) => void)[]>();
    constructor(readonly url: string) {}
    addEventListener(type: string, fn: (e: { type: string; data: string }) => void) {
      this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
    }
    send(type: string, data: string) {
      for (const fn of this.listeners.get(type) ?? []) fn({ type, data });
    }
  }
  const run = () => {
    const win: { __earlyStream?: { src: Source; events: { type: string; data: string }[]; adopted?: boolean } } = {};
    new Function("window", "EventSource", inline[0])(win, Source);
    return win.__earlyStream!;
  };

  it("runs before the bundle's module script, so the snapshot is requested while the bundle loads", () => {
    expect(inline).toHaveLength(1);
    expect(page.indexOf("<script>")).toBeLessThan(page.indexOf('<script type="module"'));
    expect(run().src.url).toBe("/api/events");
  });

  it("holds every event type the page listens for, in the order they arrive", () => {
    const early = run();
    const types = [...streamSource.matchAll(/addEventListener\("(\w+)"/g)].map(([, t]) => t);
    expect(types.length).toBeGreaterThan(5);

    for (const [i, type] of types.entries()) early.src.send(type, `{"n":${i}}`);

    expect(early.events).toEqual(types.map((type, i) => ({ type, data: `{"n":${i}}` })));
  });

  it("stops holding events once the page listens itself", () => {
    const early = run();
    early.src.send("snapshot", "{}");
    early.adopted = true;
    early.src.send("task", "{}");

    expect(early.events).toEqual([{ type: "snapshot", data: "{}" }]);
  });
});
