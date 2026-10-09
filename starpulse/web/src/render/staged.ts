/**
 * Runs a two-step job as two later tasks, so the event that asked for it ends first and neither step shares a task with the other:
 * `build` returns the step that applies what it made. A newer call drops the unfinished chain it overtakes, since it covers the same ground.
 */
export function staged() {
  let gen = 0, timer: ReturnType<typeof setTimeout> | undefined;
  const later = (build: () => () => void) => {
    const mine = ++gen;
    clearTimeout(timer);
    timer = setTimeout(() => {
      const apply = build();
      timer = setTimeout(() => mine === gen && apply(), 0);
    }, 0);
  };
  later.cancel = () => {
    gen++;
    clearTimeout(timer);
  };
  return later;
}
