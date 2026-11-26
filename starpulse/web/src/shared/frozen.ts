import type { Frozen } from "../api";

/** The hover text of a frozen task on every surface: who froze it and why. */
export const frozenNote = (f: Frozen): string => `Frozen by ${f.by}: ${f.reason}`;
