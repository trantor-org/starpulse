// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { execFileSync } from "node:child_process";
// @ts-expect-error Node-only, as above.
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
// @ts-expect-error Node-only, as above.
import { tmpdir } from "node:os";
// @ts-expect-error Node-only, as above.
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

/** The entry chunk of the build that held every view in it (main before TASK-3337), in bytes. The split entry must be smaller. */
const UNSPLIT_ENTRY_BYTES = 566_872;
/** The views the Board does not draw first: each loads on demand, so none belongs to the entry chunk. */
const LAZY_VIEWS = [
  "features/kanban/Kanban.tsx",
  "features/dags/Dags.tsx",
  "features/admin/Admin.tsx",
  "features/forwarding/ForwardingCard.tsx",
  "features/orbit/OrbitCard.tsx",
];

const root = new URL("../..", import.meta.url).pathname;
const vite = join(root, "node_modules/.bin/vite");

/** `vite build` into `out` as production, with source maps so each chunk says which source files it holds. */
function build(out: string, ...args: string[]): void {
  execFileSync(vite, ["build", "--outDir", out, "--emptyOutDir", "--sourcemap", "--logLevel", "silent", ...args], {
    cwd: root,
    // @ts-expect-error Node-only, as above.
    env: { ...process.env, NODE_ENV: "production" },
  });
}

/** Each script chunk in a build's `assets/`: its size and the source files it holds. */
function chunks(out: string): { name: string; bytes: number; sources: string[] }[] {
  return readdirSync(join(out, "assets"))
    .filter((f: string) => f.endsWith(".js"))
    .map((name: string) => ({
      name,
      bytes: readFileSync(join(out, "assets", name)).length,
      sources: JSON.parse(readFileSync(join(out, "assets", `${name}.map`), "utf8")).sources as string[],
    }));
}

const holds = (sources: string[], view: string) => sources.some((s) => s.endsWith(view));

describe("the built page", () => {
  let served: string, oneFile: string;
  beforeAll(() => {
    served = mkdtempSync(join(tmpdir(), "starpulse-served-"));
    oneFile = mkdtempSync(join(tmpdir(), "starpulse-one-file-"));
    build(served);
    build(oneFile, "--mode", "one-file");
  }, 120_000);
  afterAll(() => {
    rmSync(served, { recursive: true, force: true });
    rmSync(oneFile, { recursive: true, force: true });
  });

  it("evaluates a smaller entry chunk than the unsplit build, with none of the views the Board does not draw first", () => {
    const html = readFileSync(join(served, "index.html"), "utf8");
    const entry = /<script type="module"[^>]*src="\/assets\/([^"]+)"/.exec(html)![1];
    const main = chunks(served).find((c) => c.name === entry)!;
    expect(main.bytes).toBeLessThan(UNSPLIT_ENTRY_BYTES);
    expect(LAZY_VIEWS.filter((v) => holds(main.sources, v))).toEqual([]);
  });

  it("still ships every view, each in a chunk the page loads on demand", () => {
    const all = chunks(served).flatMap((c) => c.sources);
    expect(LAZY_VIEWS.filter((v) => !holds(all, v))).toEqual([]);
  });

  it("builds the one-file mode as a single script holding every view, so the demo needs no server to open one", () => {
    const scripts = chunks(oneFile);
    expect(scripts).toHaveLength(1);
    expect(LAZY_VIEWS.filter((v) => !holds(scripts[0].sources, v))).toEqual([]);
  });
});
