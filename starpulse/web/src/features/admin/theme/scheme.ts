// A color pack and a background become the page's tokens. A pack names its palette (c) and which palette color plays each status
// role (r); a background is the neutral ramp the roles sit on. Every role is fitted to read on the chosen background, so any pack
// goes on any background, and a base16 or base24 scheme imports as one of each.
import { contrast, deltaE, hex, hueGap, lch, mixLch, type Lch } from "./color";
import packsJson from "./packs.json";

/** A palette key, a #rrggbb, or a mix of two of them at t. */
export type Val = string | [Val, Val, number];
export interface Pack { name: string; vibe?: string; src?: { label: string }; c: Record<string, string>; r: Record<string, Val>; x?: Record<string, string> }
export const NEUTRALS = ["bg0", "bg1", "surface", "stack", "track", "faint", "muted", "ink2", "ink"] as const;
export type Neutrals = Record<(typeof NEUTRALS)[number], string>;
export interface Nudge { key: string; from: string; to: string }

export const ROLES = ["ok", "run", "fail", "danger", "agent", "hold", "waits", "ready", "released", "phase", "submachine"] as const;
/** The roles that must not be mistaken for each other on the Star Map; danger and submachine are derived and sit beside their parents. */
export const DISTINCT = ["ok", "run", "fail", "agent", "hold", "waits", "ready", "released", "phase"] as const;
const TARGET_HUE: Record<string, number> = { ok: 145, run: 90, fail: 22, hold: 55, agent: 305, waits: 215, ready: 255, released: 180, phase: 280 };
/** Below this OKLab distance two statuses read as one color: the import is refused. Below WARN_DE it is allowed with a warning. */
export const REFUSE_DE = 0.035;
export const WARN_DE = 0.05;
/** A background's surface must be darker than this OKLCH lightness: the page is dark only. */
export const MAX_SURFACE_L = 0.3;

export const BUILTIN: Record<string, Pack> = packsJson.packs as unknown as Record<string, Pack>;
export const SLATE: Neutrals = packsJson.slate;

export function resolve(v: Val, c: Record<string, string>): Lch {
  if (Array.isArray(v)) return mixLch(resolve(v[0], c), resolve(v[1], c), v[2]);
  return lch(v.startsWith("#") ? v : c[v]);
}

/** Walks OKLCH lightness up, keeping chroma and hue, until the color clears `min` against every background. */
function fit(key: string, col: Lch, against: string[], min: number, nudged: Nudge[] | null) {
  const from = hex(col);
  let [l, out] = [col[0], from];
  for (let i = 0; i < 200 && against.some((b) => contrast(out, b) < min); i++) {
    l = Math.min(1, l + 0.005);
    out = hex([l, col[1], col[2]]);
  }
  if (nudged && out !== from) nudged.push({ key, from, to: out });
  return out;
}

/** The background's own tokens, its text colors lifted to read on its surface. */
export function neutrals(n: Neutrals, nudged: Nudge[] = []) {
  const t: Record<string, string> = { bg0: n.bg0, bg1: n.bg1, surface: n.surface, stack: n.stack, track: n.track, faint: n.faint };
  t.muted = fit("muted", lch(n.muted), [n.surface], 4.5, nudged);
  t["ink-2"] = fit("ink-2", lch(n.ink2), [n.surface], 7, nudged);
  t.ink = fit("ink", lch(n.ink), [n.surface], 7, nudged);
  t.ghost = hex(mixLch(lch(t.track), lch(t.faint), 0.5));
  t.slate = hex(mixLch(lch(t.muted), lch(t["ink-2"]), 0.45));
  return t;
}

/** Every token a pack on a background draws: the neutrals, then each role with its -hi and -text, fitted to the surface. */
export function build(p: Pack, n: Neutrals) {
  const nudged: Nudge[] = [];
  const t = neutrals(n, nudged);
  const against = [t.surface, t.bg0], ink = lch(t.ink);
  const role = (k: string, col: Lch, pal: boolean) => {
    t[k] = fit(k, col, against, 3, pal ? nudged : null);
    // Toward the ink's lightness and chroma but on the role's own hue: the ink is near grey, so its hue is noise.
    const base = lch(t[k]), toward: Lch = [ink[0], ink[1], base[2]];
    t[`${k}-hi`] = hex(mixLch(base, toward, 0.55));
    t[`${k}-text`] = fit(`${k}-text`, mixLch(base, toward, 0.3), against, 4.5, null);
  };
  for (const k of ROLES.slice(0, -1)) role(k, resolve(p.r[k], p.c), true);
  if (p.r.submachine) role("submachine", resolve(p.r.submachine, p.c), true);
  else {
    const [l, c, h] = lch(t.phase);
    role("submachine", [l - 0.08, c * 0.55, h], false);
  }
  Object.assign(t, p.x);
  return { t, nudged };
}

/** The two statuses that look most alike, and how far apart they are. */
export function closest(t: Record<string, string>): [number, string, string] {
  let best: [number, string, string] = [Infinity, "", ""];
  DISTINCT.forEach((a, i) => DISTINCT.slice(i + 1).forEach((b) => {
    const d = deltaE(t[a], t[b]);
    if (d < best[0]) best = [d, a, b];
  }));
  return best;
}

const shift = (h: string, dl: number) => {
  const [l, c, hue] = lch(h);
  return hex([l + dl, c, hue]);
};

/** A dark ramp from one picked color: Slate's lightness steps and chroma ratios, on the picked hue and chroma. */
export function rampFrom(pick: string): Neutrals {
  const [L, C, H] = lch(pick), base = lch(SLATE.surface);
  const step = (k: keyof Neutrals): string => {
    if (k === "surface") return pick;
    const [l, c] = lch(SLATE[k]);
    // Text steps keep at most Slate's own tint, so a saturated pick tints the page without tinting its words.
    const tint = Math.min((C * c) / Math.max(base[1], 1e-3), l > 0.6 ? Math.max(c, 0.03) : 0.09);
    return hex([L + (l - base[0]), tint, H]);
  };
  return Object.fromEntries(NEUTRALS.map((k) => [k, step(k)])) as Neutrals;
}

/** Why a ramp cannot be a background, or null when it can. */
export const bgRefusal = (n: Neutrals) =>
  lch(n.surface)[0] >= MAX_SURFACE_L ? `Backgrounds are dark only: this surface is ${Math.round(lch(n.surface)[0] * 100)}% light, and it must be under ${MAX_SURFACE_L * 100}%.` : null;

const ACCENTS = ["08", "09", "0A", "0B", "0C", "0D", "0E", "0F"].map((s) => `base${s}`);
const BRIGHTS = ["12", "13", "14", "15", "16", "17"].map((s) => `base${s}`);

/** A base16 or base24 YAML scheme as a pack (accents matched to roles by hue) and a background (its base00-05 ramp). */
export function fromBase16(text: string): { name: string; author?: string; pack: Pack; bg: Neutrals } {
  const c: Record<string, string> = {};
  let name = "", author = "";
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\s*(base[0-9A-Fa-f]{2})\s*:\s*["']?#?([0-9a-fA-F]{6})\b/);
    if (m) {
      c[`base${m[1].slice(4).toUpperCase()}`] = `#${m[2].toLowerCase()}`;
      continue;
    }
    const kv = line.match(/^\s*(name|scheme|author)\s*:\s*["']?([^"'\n]+?)["']?\s*$/);
    if (kv?.[1] === "author") author = kv[2];
    else if (kv) name = kv[2];
  }
  const missing = ["base00", "base02", "base03", "base05", ...ACCENTS].filter((k) => !c[k]);
  if (missing.length) throw new Error(`Not a base16 or base24 scheme: it has no ${missing.join(", ")}.`);
  const at = (a: string, b: string, t: number) => hex(mixLch(lch(c[a]), lch(c[b]), t));
  const bg: Neutrals = {
    surface: c.base00, bg0: shift(c.base00, -0.035), bg1: shift(c.base00, -0.017), stack: at("base00", "base02", 0.5),
    track: c.base02, faint: c.base03, muted: at("base03", "base05", 0.35), ink2: at("base05", "base03", 0.2), ink: c.base05,
  };
  const slots = (ks: string[]) => ks.filter((k) => c[k]).map((k) => ({ k, lch: lch(c[k]) })).filter((s) => s.lch[1] > 0.04);
  const r: Record<string, Val> = {}, used = new Set<string>();
  const assign = (pool: { k: string; lch: Lch }[]) => {
    const pairs: [number, string, string][] = [];
    for (const [role, h] of Object.entries(TARGET_HUE)) for (const s of pool) {
      const gap = hueGap(s.lch[2], h);
      if (gap <= 40) pairs.push([gap, role, s.k]);
    }
    pairs.sort((a, b) => a[0] - b[0]);
    for (const [, role, k] of pairs) if (!r[role] && !used.has(c[k])) {
      r[role] = k;
      used.add(c[k]);
    }
  };
  assign(slots(ACCENTS));
  assign(slots(BRIGHTS));
  const via = (role: string, a: string, b: string) => {
    if (!r[role] && r[a] && r[b]) r[role] = [r[a], r[b], 0.5];
  };
  via("phase", "ready", "agent");
  via("waits", "ready", "released");
  via("released", "waits", "ok");
  const pool = slots(ACCENTS).map((s) => s.lch);
  const median = (i: number) => pool.map((p) => p[i]).sort((a, b) => a - b)[pool.length >> 1] ?? 0.75;
  // A role the scheme has no hue for gets one at the scheme's typical lightness, held below 0.78 so the gamut leaves blues and violets
  // enough chroma to tell apart.
  for (const [role, h] of Object.entries(TARGET_HUE)) if (!r[role]) r[role] = hex([Math.min(median(0), 0.78), Math.max(median(1), 0.12), h]);
  r.danger = [r.fail, r.hold, 0.15];
  name ||= "Imported scheme";
  return { name, author: author || undefined, pack: { name, src: { label: author ? `Imported · ${author}` : "Imported" }, c, r }, bg };
}
