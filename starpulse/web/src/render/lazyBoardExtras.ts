// Fold and machine-ledger drawing the Board's first paint does not need. Prefetch after
// starpulse:board-drawn so a drill finds them loaded; ensure* waits if a click races the prefetch.

type FoldMod = typeof import("./foldDraw");
type LedgerMod = typeof import("./machineLedgerDraw");

let foldP: Promise<FoldMod> | undefined;
let ledgerP: Promise<LedgerMod> | undefined;

export const loadFold = (): Promise<FoldMod> => (foldP ??= import("./foldDraw"));
export const loadMachineLedger = (): Promise<LedgerMod> => (ledgerP ??= import("./machineLedgerDraw"));

/** Starts both loads when the browser is idle after the board has drawn. */
export function prefetchBoardExtras(): () => void {
  const go = () => {
    void loadFold();
    void loadMachineLedger();
  };
  if (typeof requestIdleCallback === "function") {
    const id = requestIdleCallback(go, { timeout: 2000 });
    return () => cancelIdleCallback(id);
  }
  const id = setTimeout(go, 200);
  return () => clearTimeout(id);
}

export type FoldDrawing = ReturnType<FoldMod["foldDraw"]>;
export type MachineLedgerDrawing = ReturnType<LedgerMod["machineLedger"]>;
