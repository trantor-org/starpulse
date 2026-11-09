/** Work only a shown canvas needs: `request` runs it at once while shown, and while hidden notes it for the next `show(true)` or `settle`. */
export function whenShown(run: () => void) {
  let shown = true, stale = false;
  const settle = () => {
    if (!stale) return;
    stale = false;
    run();
  };
  return {
    request() {
      if (shown) run();
      else stale = true;
    },
    show(on: boolean) {
      shown = on;
      if (on) settle();
    },
    settle,
  };
}
