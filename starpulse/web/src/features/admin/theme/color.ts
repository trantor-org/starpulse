// OKLab and OKLCH (Björn Ottosson's matrices) and WCAG contrast, the only color math a theme needs: L runs 0..1, C about 0..0.4.
export type Lch = [number, number, number];
export type Rgb = [number, number, number];

const toLinear = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
const toGamma = (v: number) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055);

/** A #rrggbb as 0..1 channels. */
export const rgbOf = (hex: string): Rgb => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255) as Rgb;

export function labOfRgb(c: Rgb): Rgb {
  const [r, g, b] = c.map(toLinear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}

export const lab = (hex: string) => labOfRgb(rgbOf(hex));

export function lchOfRgb(c: Rgb): Lch {
  const [L, a, b] = labOfRgb(c);
  return [L, Math.hypot(a, b), ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360];
}

export const lch = (hex: string) => lchOfRgb(rgbOf(hex));

function linearOf([L, C, H]: Lch): Rgb {
  const a = C * Math.cos((H * Math.PI) / 180), b = C * Math.sin((H * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3, s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
}

const inGamut = (v: Rgb) => v.every((x) => x >= -1e-4 && x <= 1 + 1e-4);

/** An OKLCH color as 0..255 sRGB, its chroma cut until it fits the gamut so hue and lightness hold. */
export function rgb255([L, C, H]: Lch): Rgb {
  const l = Math.min(1, Math.max(0, L));
  let v = linearOf([l, C, H]);
  if (!inGamut(v)) {
    let lo = 0, hi = C;
    for (let i = 0; i < 24; i++) {
      const mid = (lo + hi) / 2;
      if (inGamut(linearOf([l, mid, H]))) lo = mid;
      else hi = mid;
    }
    v = linearOf([l, lo, H]);
  }
  return v.map((x) => Math.round(Math.min(1, Math.max(0, toGamma(Math.max(0, x)))) * 255)) as Rgb;
}

export const hex = (c: Lch) => `#${rgb255(c).map((x) => x.toString(16).padStart(2, "0")).join("")}`;

const luminance = (h: string) => {
  const [r, g, b] = rgbOf(h).map(toLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

/** The WCAG contrast ratio of two colors, 1..21. */
export function contrast(a: string, b: string) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** How far apart two colors look: the OKLab distance, where 0.02 is about a just-noticeable difference. */
export const deltaE = (a: string, b: string) => {
  const p = lab(a), q = lab(b);
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
};

/** Mixes in OKLCH along the shorter way round the hue circle; a grey takes the other color's hue. */
export function mixLch([l1, c1, h1]: Lch, [l2, c2, h2]: Lch, t: number): Lch {
  const a = c1 > 1e-4 ? h1 : h2, b = c2 > 1e-4 ? h2 : h1;
  const d = ((b - a + 540) % 360) - 180;
  return [l1 + (l2 - l1) * t, c1 + (c2 - c1) * t, (a + d * t + 360) % 360];
}

export const hueGap = (a: number, b: number) => Math.abs(((a - b + 540) % 360) - 180);
