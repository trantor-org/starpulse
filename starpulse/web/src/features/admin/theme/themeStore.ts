// The theme every device draws: a color pack and a background, each built in or imported, kept by the server (`theme` of /api/admin).
// Every change rebuilds the tokens and hands them to `apply`, which redraws the page in them.
import { apiFetch } from "../../../api/apiFetch";
import { readSettings, writeSettings, type Saved, type Settings } from "../adminSettings";
import { BUILTIN, SLATE, build, type Neutrals, type Pack } from "./scheme";

export interface SavedPack { id: string; pack: Pack }
export interface SavedBg { id: string; name: string; n: Neutrals }
export interface ThemePrefs { pack: string; bg: string; packs: SavedPack[]; bgs: SavedBg[] }
export const THEME_DEFAULTS: ThemePrefs = { pack: "starpulse", bg: "slate", packs: [], bgs: [] };
export type Tokens = Record<string, string>;

const list = <T>(v: unknown, ok: (x: Record<string, unknown>) => boolean) =>
  (Array.isArray(v) ? v.filter((x) => typeof x === "object" && x !== null && ok(x)) : []) as T[];

export function loadTheme(raw: unknown): ThemePrefs {
  const r = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const packs = list<SavedPack>(r.packs, (x) => typeof x.id === "string" && typeof x.pack === "object");
  const bgs = list<SavedBg>(r.bgs, (x) => typeof x.id === "string" && typeof x.n === "object");
  const pack = typeof r.pack === "string" && (BUILTIN[r.pack] || packs.some((p) => p.id === r.pack)) ? r.pack : THEME_DEFAULTS.pack;
  const bg = typeof r.bg === "string" && bgs.some((b) => b.id === r.bg) ? r.bg : THEME_DEFAULTS.bg;
  return { pack, bg, packs, bgs };
}

const newId = () => `u${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

export class ThemeStore {
  private prefs: ThemePrefs = THEME_DEFAULTS;
  private outcome: Saved = { kind: "idle" };
  private listeners = new Set<() => void>();

  /** Starts on the built-in theme; `adopt` brings the server's in once it arrives. */
  constructor(private apply: (t: Tokens) => void = () => {}, private fetcher: typeof apiFetch = apiFetch) {
    apply(this.tokens());
  }

  get = () => this.prefs;
  /** How the last change ended. */
  saved = () => this.outcome;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  packOf = (id: string): Pack => BUILTIN[id] ?? this.prefs.packs.find((p) => p.id === id)?.pack ?? BUILTIN.starpulse;
  bgOf = (id: string): Neutrals => this.prefs.bgs.find((b) => b.id === id)?.n ?? SLATE;
  tokens = (): Tokens => build(this.packOf(this.prefs.pack), this.bgOf(this.prefs.bg)).t;

  adopt = (settings: Settings) => this.set(loadTheme(settings.theme), false);
  private keep = async (theme: ThemePrefs) => {
    this.outcome = await writeSettings(this.fetcher, { theme });
    if (this.outcome.kind === "refused") {
      const held = await readSettings(this.fetcher);
      if (held) this.set(loadTheme(held.theme), false);
    }
    for (const fn of this.listeners) fn();
  };

  choosePack = (pack: string) => this.set({ ...this.prefs, pack });
  chooseBg = (bg: string) => this.set({ ...this.prefs, bg });

  /** Saves an imported pack, and its background when `bg` is given, and switches to them. */
  addPack = (pack: Pack, bg?: Neutrals) => {
    const id = newId(), packs = [...this.prefs.packs, { id, pack }];
    if (!bg) return this.set({ ...this.prefs, packs, pack: id });
    const bid = `${id}b`;
    this.set({ ...this.prefs, packs, pack: id, bgs: [...this.prefs.bgs, { id: bid, name: pack.name, n: bg }], bg: bid });
  };
  addBg = (name: string, n: Neutrals) => {
    const id = newId();
    this.set({ ...this.prefs, bgs: [...this.prefs.bgs, { id, name, n }], bg: id });
  };
  renamePack = (id: string, name: string) =>
    this.set({ ...this.prefs, packs: this.prefs.packs.map((p) => (p.id === id ? { id, pack: { ...p.pack, name } } : p)) });
  renameBg = (id: string, name: string) => this.set({ ...this.prefs, bgs: this.prefs.bgs.map((b) => (b.id === id ? { ...b, name } : b)) });
  /** Deleting the pack or background in use falls back to the built-in one. */
  deletePack = (id: string) =>
    this.set({ ...this.prefs, packs: this.prefs.packs.filter((p) => p.id !== id), pack: this.prefs.pack === id ? THEME_DEFAULTS.pack : this.prefs.pack });
  deleteBg = (id: string) =>
    this.set({ ...this.prefs, bgs: this.prefs.bgs.filter((b) => b.id !== id), bg: this.prefs.bg === id ? THEME_DEFAULTS.bg : this.prefs.bg });

  /** Draws `next` at once and, when `keep`, sends the whole theme; a refused write draws what the server holds. */
  private set(next: ThemePrefs, keep = true) {
    const redraw = !keep || next.pack !== this.prefs.pack || next.bg !== this.prefs.bg;
    this.prefs = next;
    if (redraw) this.apply(this.tokens());
    for (const fn of this.listeners) fn();
    if (keep) void this.keep(next);
  }
}
