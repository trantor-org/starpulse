/** Faces the Board's first canvas draw measures and paints. Inter 500 and JetBrains Mono are chrome and panels after that frame. */
export const BOARD_FACES = ["300 12px Inter", "400 12px Inter"] as const;

/** Faces the page loads after `starpulse:board-drawn`, so they do not hold the stream open. */
export const LATE_FACES = ["500 12px Inter", '400 12px "JetBrains Mono"'] as const;

/** Every @font-face in style.css: the board's first-paint faces, then the late ones. */
export const FACES = [...BOARD_FACES, ...LATE_FACES] as const;

const loadAll = (faces: readonly string[], fonts: Pick<FontFaceSet, "load"> | undefined) => {
  if (!fonts?.load) return Promise.resolve();
  return Promise.allSettled(faces.map((face) => fonts.load(face))).then(() => undefined);
};

/** Resolves once every first-paint face has loaded, or failed: a font that cannot load draws in the fallback face rather than leaving the canvas blank. */
export function fontsReady(fonts: Pick<FontFaceSet, "load"> = document.fonts): Promise<void> {
  return loadAll(BOARD_FACES, fonts);
}

/** Starts loading the faces the navigator, rail and panels use, after the board has drawn. */
export function loadLateFonts(fonts?: Pick<FontFaceSet, "load">): Promise<void> {
  return loadAll(LATE_FACES, fonts ?? (typeof document !== "undefined" ? document.fonts : undefined));
}

let started: Promise<void> | undefined;

/** `fontsReady`, begun once: main.tsx starts the loads at page start-up and the renderer joins the same promise when it opens its stream. */
export const loadFonts = (fonts?: Pick<FontFaceSet, "load">): Promise<void> => (started ??= fontsReady(fonts));
