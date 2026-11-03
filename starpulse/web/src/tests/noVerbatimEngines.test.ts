import { describe, expect, it } from "vitest";

// A mockup engine pasted in whole (fixed frame, own chrome) behind a whole-file lint disable passed every guard once
// (TASK-8665). Only the files listed here may still carry one; the list shrinks to empty and never grows.
const ALLOWED = ["/src/features/level/sunsEngine.js"];

const sources = import.meta.glob<string>(["/src/**/*.{js,jsx,ts,tsx}", "!/src/**/*.test.*", "!/src/tests/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const WHOLE_FILE_DISABLE = /\/\*\s*(?:eslint|oxlint)-disable(?!-)/;
const VERBATIM_HEADER = /ported verbatim/i;

describe("checked-in mockup engines", () => {
  it("refuses a whole-file lint disable or a 'ported verbatim' header outside the allow-list", () => {
    const offenders = Object.entries(sources)
      .filter(([, text]) => WHOLE_FILE_DISABLE.test(text) || VERBATIM_HEADER.test(text))
      .map(([path]) => path)
      .filter((path) => !ALLOWED.includes(path));
    expect(offenders).toEqual([]);
  });

  it("keeps no allow-list entry for a file that is gone or no longer offends", () => {
    const stale = ALLOWED.filter((path) => {
      const text = sources[path];
      return text === undefined || !(WHOLE_FILE_DISABLE.test(text) || VERBATIM_HEADER.test(text));
    });
    expect(stale).toEqual([]);
  });
});
