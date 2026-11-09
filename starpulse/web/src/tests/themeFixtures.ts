// What a test needs to draw in a chosen theme: a built-in pack's tokens, applied as the Admin picker applies them (the :root vars, the
// `sp:theme` event and readTokens), and a way back to the StarPulse pack.
import { applyTheme } from "../features/admin/theme/apply";
import { BUILTIN, SLATE, build } from "../features/admin/theme/scheme";

export { applyTheme };

export const packTokens = (pack: keyof typeof BUILTIN) => build(BUILTIN[pack], SLATE).t;

/** Applies a built-in pack on Slate and returns its tokens. */
export function applyPack(pack: keyof typeof BUILTIN) {
  const tokens = packTokens(pack);
  applyTheme(tokens);
  return tokens;
}
