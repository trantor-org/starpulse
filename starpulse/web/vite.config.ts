import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Built into ../static, which starpulse.server serves at the site root. The
// output is gitignored: the repo keeps source, and `pnpm --filter flow-view
// build` puts the bundle in place.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../static", emptyOutDir: true },
  // `pnpm --filter flow-view dev` reads a running starpulse.server's snapshot.
  server: { proxy: { "/api": "http://127.0.0.1:8766" } },
  // The stylesheet is read for real so a test can hold its scrolling rules (`src/scroll.test.ts`).
  test: { environment: "node", css: { include: /style\.css/ } },
});
