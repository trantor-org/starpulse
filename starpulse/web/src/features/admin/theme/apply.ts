// Writes the theme's tokens onto :root as CSS custom properties, so every page color follows them, and keeps the last values for the
// canvas code, which cannot read CSS per pixel. A change that alters any token dispatches `sp:theme` once; the canvases listen for it.
import type { Tokens } from "./themeStore";

const current: Tokens = {};

export function applyTheme(tokens: Tokens): void {
  const style = document.documentElement.style;
  let changed = false;
  for (const [key, value] of Object.entries(tokens)) {
    if (current[key] === value) continue;
    style.setProperty(`--${key}`, value);
    current[key] = value;
    changed = true;
  }
  if (changed) window.dispatchEvent(new Event("sp:theme"));
}

/** The token values last applied, for canvas code to read. */
export const readTokens = (): Tokens => ({ ...current });
