// Structural equality that stops at a shared reference, and the fold that keeps the old reference for what a fresh read left unchanged.
// A delta arrives as freshly parsed JSON, so every object in it is new; keeping the old one for each unchanged entry lets the rest of
// the page tell "this entry changed" by identity, and spend its work on what changed rather than on everything it holds.

const plain = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && (Array.isArray(x) || Object.getPrototypeOf(x) === Object.prototype);

/** Whether `a` and `b` hold the same JSON data; values that are the same reference are not looked into. */
export function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!plain(a) || !plain(b) || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((k) => k in b && same(a[k], b[k]));
}

/**
 * `next` with every part that holds what `prev` does replaced by `prev`'s own reference, and `prev` itself when nothing differs. An array's
 * entries pair by position, or by `key` when it names each entry, so a reorder or an insert keeps the entries that moved. Nothing is allocated
 * for a part that did not change: the page calls this on every event, and most events change little.
 */
export function keep<T>(prev: T, next: T, key?: T extends (infer E)[] ? (x: E) => string : never): T {
  if (prev === next || !plain(prev) || !plain(next) || Array.isArray(prev) !== Array.isArray(next)) return next;
  if (!key && same(prev, next)) return prev;
  return rebuild(prev, next, key as ((x: unknown) => string) | undefined) as T;
}

/** `next` with each of its parts that `prev` also holds replaced by `prev`'s; the caller has found the two to differ. */
function rebuild(prev: Record<string, unknown>, next: Record<string, unknown>, by?: (x: unknown) => string): unknown {
  const pair = (old: unknown, x: unknown) => (old === x || !plain(old) || !plain(x) || Array.isArray(old) !== Array.isArray(x) ? x : same(old, x) ? old : rebuild(old, x));
  if (Array.isArray(next)) {
    const old = prev as unknown as unknown[], at = by ? new Map<string, unknown>(old.map((x) => [by(x), x])) : null;
    const out = next.map((x: unknown, i) => pair(at ? at.get(by!(x)) : old[i], x));
    return out.length === old.length && out.every((x, i) => x === old[i]) ? prev : out;
  }
  return Object.fromEntries(Object.keys(next).map((k) => [k, pair(prev[k], next[k])]));
}
