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
 * entries pair by position, or by `key` when it names each entry, so a reorder or an insert keeps the entries that moved.
 */
export function keep<T>(prev: T, next: T, key?: T extends (infer E)[] ? (x: E) => string : never): T {
  if (prev === next || !plain(prev) || !plain(next) || Array.isArray(prev) !== Array.isArray(next)) return next;
  if (Array.isArray(next)) {
    const old = prev as unknown[], by = key as ((x: unknown) => string) | undefined, at = by ? new Map<string, unknown>(old.map((x) => [by(x), x])) : null;
    const out = next.map((x: unknown, i) => keep(at ? at.get(by!(x)) : old[i], x));
    return (out.length === old.length && out.every((x, i) => x === old[i]) ? prev : out) as T;
  }
  const old = prev as Record<string, unknown>, keys = Object.keys(next), out = Object.fromEntries(keys.map((k) => [k, keep(old[k], next[k])]));
  return (keys.length === Object.keys(old).length && keys.every((k) => out[k] === old[k]) ? prev : out) as T;
}
