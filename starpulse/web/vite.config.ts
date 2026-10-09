import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Built into ../static, which starpulse._internal.api.server serves at the site root. The
// output is gitignored: the repo keeps source, and `pnpm --filter flow-view
// build` puts the bundle in place. The views the Board does not draw first are
// chunks the page loads on demand (src/lazyViews.ts).
//
// `--mode one-file` builds the same page as one script, into ../static/one-file, for
// `starpulse._internal.cli.demo`: a demo is a single HTML file with no server to fetch a chunk
// from, so it inlines that script. `pnpm run build` runs both, the page first, since
// its build empties ../static.
export default defineConfig(({ mode }) => {
  const oneFile = mode === "one-file";
  return {
    plugins: [react()],
    build: {
      outDir: oneFile ? "../static/one-file" : "../static",
      emptyOutDir: !oneFile,
      rolldownOptions: { output: { codeSplitting: !oneFile } },
    },
    // `pnpm --filter flow-view dev` reads a running starpulse._internal.api.server's snapshot.
    server: { proxy: { "/api": "http://127.0.0.1:8766" } },
    // The stylesheet is read for real so a test can hold its scrolling rules (`src/shared/scroll.test.ts`).
    // A cold CI runner transforms every module on the first test of a file, which can pass the 5 s default.
    test: { environment: "node", testTimeout: 15_000, css: { include: /style\.css/ } },
  };
});
