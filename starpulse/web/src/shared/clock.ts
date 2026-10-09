// Every time the page shows, written in Arizona time in the clock the Admin view chose. Formatting happens here, at the source, so
// no text is rewritten after the fact.
// Arizona keeps UTC-7 all year with no daylight saving time, so its wall clock is fixed arithmetic. An Intl.DateTimeFormat built at module
// load cost ~20 ms of the cold first paint on the ai-vm-1 profile (ICU data load) for the same strings.
const MST_MS = -7 * 3600 * 1000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export type ClockMode = "24" | "12";

function parts(ms: number) {
  const d = new Date(ms + MST_MS);
  const m = d.getUTCMinutes();
  return { year: d.getUTCFullYear(), month: MONTHS[d.getUTCMonth()], day: d.getUTCDate(), hour: d.getUTCHours(), minute: m < 10 ? `0${m}` : String(m) };
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
