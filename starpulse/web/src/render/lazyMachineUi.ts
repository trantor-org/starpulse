/** Machine-across-the-top layout and scroll: the Board's first paint does not need it. Prefetch after starpulse:board-drawn. */

export type MachineUi = {
  ledgerTop: typeof import("../features/level/machineLedger").ledgerTop;
  sizes: typeof import("../features/level/machineLedger").sizes;
  nestsOf: typeof import("../features/level/machineChain").nestsOf;
  laneRows: typeof import("../features/level/machineLanes").laneRows;
  laneContent: typeof import("../features/level/machineScroll").laneContent;
  shownRows: typeof import("../features/level/machinePaging").shownRows;
  rankRows: typeof import("../features/level/machineRows").rankRows;
  firstOpened: typeof import("../features/level/machineRows").firstOpened;
  rowMeta: typeof import("../features/level/machineRows").rowMeta;
  asked: typeof import("../features/level/machinePaging").asked;
  arrived: typeof import("../features/level/machinePaging").arrived;
  failed: typeof import("../features/level/machinePaging").failed;
  nextQuery: typeof import("../features/level/machinePaging").nextQuery;
  paging: typeof import("../features/level/machinePaging").paging;
  reveal: typeof import("../features/level/machinePaging").reveal;
  RETRY: typeof import("../features/level/machinePaging").RETRY;
  wantNext: typeof import("../features/level/machinePaging").wantNext;
  dragTo: typeof import("../features/level/machineScroll").dragTo;
  inputGoal: typeof import("../features/level/machineScroll").inputGoal;
  revealGoal: typeof import("../features/level/machineScroll").revealGoal;
};

let ui: MachineUi | null = null;
let uiP: Promise<MachineUi> | undefined;

export const machineUi = (): MachineUi | null => ui;

export const loadMachineUi = (): Promise<MachineUi> => (uiP ??= Promise.all([
  import("../features/level/machineLedger"),
  import("../features/level/machineChain"),
  import("../features/level/machineLanes"),
  import("../features/level/machineScroll"),
  import("../features/level/machinePaging"),
  import("../features/level/machineRows"),
]).then(([ml, mc, mlanes, ms, mp, mr]) => {
  ui = {
    ledgerTop: ml.ledgerTop,
    sizes: ml.sizes,
    nestsOf: mc.nestsOf,
    laneRows: mlanes.laneRows,
    laneContent: ms.laneContent,
    shownRows: mp.shownRows,
    rankRows: mr.rankRows,
    firstOpened: mr.firstOpened,
    rowMeta: mr.rowMeta,
    asked: mp.asked,
    arrived: mp.arrived,
    failed: mp.failed,
    nextQuery: mp.nextQuery,
    paging: mp.paging,
    reveal: mp.reveal,
    RETRY: mp.RETRY,
    wantNext: mp.wantNext,
    dragTo: ms.dragTo,
    inputGoal: ms.inputGoal,
    revealGoal: ms.revealGoal,
  };
  return ui;
}));
