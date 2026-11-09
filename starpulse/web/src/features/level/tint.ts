// A translucent tint of a theme token, written the way style.css writes one: the token mixed with transparent. The browser resolves
// `var(--name)` when it paints, so a tint follows a theme change with no redraw.
export const tint = (token: string, percent: number) => `color-mix(in srgb, var(--${token}) ${percent}%, transparent)`;
