/** One face per @font-face in style.css. The canvas measures labels to lay them out and draws them in these faces, and neither is redone when a font
 *  arrives late, so the renderer holds its first snapshot until they have loaded. */
export const FACES = ["300 12px Inter", "400 12px Inter", "500 12px Inter", '400 12px "JetBrains Mono"'] as const;

/** Resolves once every face has loaded, or failed: a font that cannot load draws in the fallback face rather than leaving the canvas blank. */
export function fontsReady(fonts: Pick<FontFaceSet, "load"> = document.fonts): Promise<void> {
  return Promise.allSettled(FACES.map((face) => fonts.load(face))).then(() => undefined);
}

let started: Promise<void> | undefined;

/** `fontsReady`, begun once: main.tsx starts the loads at page start-up and the renderer joins the same promise when it opens its stream. */
export const loadFonts = (fonts?: Pick<FontFaceSet, "load">): Promise<void> => (started ??= fontsReady(fonts));
