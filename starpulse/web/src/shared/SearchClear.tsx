import type { RefObject } from "react";

/** The ✕ at the right end of a search input while it holds text; it sits in the input's positioned parent. A press leaves the input focused, a click empties the query and puts the focus back. */
export function SearchClear({ input, value, clear }: { input: RefObject<HTMLInputElement | null>; value: string; clear: () => void }) {
  if (!value) return null;
  return (
    <button type="button" className="sx" title="Clear the search" aria-label="Clear the search"
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => { clear(); input.current?.focus(); }}>
      ✕
    </button>
  );
}
