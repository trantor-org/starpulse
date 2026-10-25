// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { LEDGER } from "./sunsLedger";
// @ts-expect-error Same Node-only import.
import { fileURLToPath } from "node:url";

describe("the drill-in's fidelity ledger", () => {
  it("has one row for each of the design record's 29 notes, in order", () => {
    expect(LEDGER.map((r) => r.n)).toEqual(Array.from({ length: 29 }, (_, i) => i + 1));
  });

  it("lists note 22 as superseded by 24, and nothing else", () => {
    expect(LEDGER.filter((r) => r.supersededBy).map((r) => [r.n, r.supersededBy])).toEqual([[22, 24]]);
  });

  it("names, for every note, a test file that exists or the live render", () => {
    for (const r of LEDGER) {
      if (r.by === "render") continue;
      const found = [r.by, `../../render/${r.by}`, `../../api/${r.by}`].some((p) => existsSync(fileURLToPath(new URL(p, import.meta.url))));
      expect(found, `#${r.n} names ${r.by}`).toBe(true);
    }
  });
});
