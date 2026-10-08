// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { FACES, fontsReady, loadFonts } from "./fonts";

const css = readFileSync(new URL("../style.css", import.meta.url), "utf8");

/** A FontFaceSet whose `load` settles when the test says so, and records what it was asked for. */
function fakeFonts(fail: string[] = []) {
  const asked: string[] = [];
  const pending: (() => void)[] = [];
  return {
    asked,
    release: () => pending.splice(0).forEach((f) => f()),
    set: {
      load: (face: string) =>
        new Promise((resolve, reject) =>
          pending.push(() => (fail.includes(face) ? reject(new Error("network")) : resolve([]))),
        ),
    } as Pick<FontFaceSet, "load">,
    track(face: string) {
      asked.push(face);
    },
  };
}

describe("the faces the canvas waits on", () => {
  it("are the ones style.css declares, so the first frame measures and draws in the page's own fonts", () => {
    const declared = [...css.matchAll(/@font-face\s*{[^}]*font-family:\s*"([^"]+)"[^}]*font-weight:\s*(\d+)/g)].map(([, family, weight]) => `${weight} ${family}`);
    expect(declared.length).toBeGreaterThan(0);
    expect(FACES.map((f) => f.replace(/ \d+px /, " ").replace(/"/g, "")).sort()).toEqual(declared.sort());
  });
});

describe("fontsReady", () => {
  it("stays pending until every face has loaded", async () => {
    const fonts = fakeFonts();
    const asked: string[] = [];
    const set = { load: (face: string) => (asked.push(face), fonts.set.load(face)) } as Pick<FontFaceSet, "load">;
    let done = false;
    const ready = fontsReady(set).then(() => (done = true));
    await Promise.resolve();
    expect(asked).toEqual([...FACES]);
    expect(done).toBe(false);
    fonts.release();
    await ready;
    expect(done).toBe(true);
  });

  it("settles when a face fails to load, so a missing font draws in the fallback rather than leaving the canvas blank", async () => {
    const fonts = fakeFonts([FACES[0]]);
    const ready = fontsReady(fonts.set);
    fonts.release();
    await expect(ready).resolves.toBeUndefined();
  });
});

describe("loadFonts", () => {
  it("starts the loads once, so the page can begin them at start-up and the renderer joins them later", async () => {
    const first = fakeFonts();
    const again = fakeFonts();
    const a = loadFonts(first.set);
    const b = loadFonts(again.set);
    first.release();
    await a;
    expect(b).toBe(a);
    again.release();
    expect(await Promise.race([b, Promise.resolve("pending")])).toBeUndefined();
  });
});
