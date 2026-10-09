// Every time the page shows, written in Arizona time in the clock the Admin view chose. Formatting happens here, at the source, so
// no text is rewritten after the fact.
const TZ = "America/Phoenix";
export type ClockMode = "24" | "12";

// One formatter: toLocaleTimeString with a time zone builds a new one per call, and the feed formats every move four times a second.
const PARTS = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hourCycle: "h23", year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function parts(ms: number) {
  const p = Object.fromEntries(PARTS.formatToParts(ms).map((x) => [x.type, x.value]));
  return { year: p.year, month: p.month, day: p.day, hour: Number(p.hour), minute: p.minute };
}

const time = (hour: number, minute: string, mode: ClockMode) =>
  mode === "24" ? `${String(hour).padStart(2, "0")}:${minute}` : `${hour % 12 || 12}:${minute} ${hour < 12 ? "am" : "pm"}`;

/** Hours and minutes of a moment in epoch seconds: `18:00` or `6:00 pm`. */
export function clockHm(sec: number, mode: ClockMode): string {
  const p = parts(sec * 1000);
  return time(p.hour, p.minute, mode);
}

/** The date and time of a snapshot: `Oct 1, 2026, 18:00`. */
export function stamp(sec: number, mode: ClockMode): string {
  const p = parts(sec * 1000);
  return `${p.month} ${p.day}, ${p.year}, ${time(p.hour, p.minute, mode)}`;
}

/** A moment as the operator reads it in a trace: `Oct 1, 18:00`. */
export function fmtAt(sec: number, mode: ClockMode = "24"): string {
  const p = parts(sec * 1000);
  return `${p.month} ${p.day}, ${time(p.hour, p.minute, mode)}`;
}

/** How long ago a span of seconds reaches: `now`, `5m`, `3h` or `2d`. */
export const ago = (seconds: number) => {
  const m = Math.max(0, Math.round(seconds / 60));
  return m < 1 ? "now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;
};
