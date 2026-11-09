import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Built into ../static, which starpulse.runtime.server serves at the site root. The
// output is gitignored: the repo keeps source, and `pnpm --filter @starpulse/web
// build` puts the bundle in place. The views the Board does not draw first are
// chunks the page loads on demand (src/lazyViews.ts).
//
// `--mode one-file` builds the same page as one script, into ../static/one-file, for
// `starpulse.cli.demo`: a demo is a single HTML file with no server to fetch a chunk
// from, so it inlines that script. `pnpm run build` runs both, the page first, since
// its build empties ../static. The demo leaves mermaid out (src/demo/noMermaid.ts): its
// bundle would add 5 MB and strings the demo leak scan refuses, so a demo's diagram is
// the mermaid source in a code fence.
export default defineConfig(({ mode }) => {
  const oneFile = mode === "one-file";
  return {
    plugins: [react()],
    resolve: { alias: oneFile ? [{ find: "mermaid", replacement: new URL("src/demo/noMermaid.ts", import.meta.url).pathname }] : [] },
    build: {
      outDir: oneFile ? "../static/one-file" : "../static",
      emptyOutDir: !oneFile,
      rolldownOptions: { output: { codeSplitting: !oneFile } },
    },
    // `pnpm --filter @starpulse/web dev` reads a running starpulse.runtime.server's snapshot.
    server: { proxy: { "/api": "http://127.0.0.1:8766" } },
    // The stylesheet is read for real so a test can hold its scrolling rules (`src/shared/scroll.test.ts`).
    // A cold CI runner transforms every module on the first test of a file, which can pass the 5 s default.
    // Test files share four worker threads, each file in its own VM context: 46 CPU-seconds a run against 99 for a process per file on
    // every core. A context's globals are jsdom's own, so `src/testSetup.ts` adds the User Timing calls jsdom lacks.
    test: { pool: "vmThreads", maxWorkers: 4, setupFiles: ["src/testSetup.ts"], environment: "node", testTimeout: 15_000, css: { include: /style\.css/ } },
  };
});
