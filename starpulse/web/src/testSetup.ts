// The vmThreads pool hands a jsdom test file jsdom's own `performance`, which has no User Timing; the page marks its first Board with it
// (`shared/boardMark.ts`). The three calls the page and its tests make are held here, one set of marks per test file.
if (typeof performance.mark !== "function") {
  const marks = new Set<string>();
  // On the prototype, where fake timers look for the methods to stand in for.
  Object.assign(Performance.prototype, {
    mark: (name: string) => void marks.add(name),
    clearMarks: (name?: string) => void (name === undefined ? marks.clear() : marks.delete(name)),
    getEntriesByName: (name: string) => (marks.has(name) ? [{ name }] : []),
  });
}
