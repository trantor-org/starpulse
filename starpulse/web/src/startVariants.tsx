// Design mockup for TASK-3016 (draft PR, never merged as is): the Kanban card's start-session control drawn in each candidate
// variant on the real page. `?start=<variant>` opens it; the bar it draws switches the variant, the text size and the density live
// and keeps the address linkable. With no `start` parameter the page is unchanged.

/** `current` is today's ▶; `compare` draws one variant per startable lane so they sit side by side. */
export type Variant = "current" | "edge" | "split" | "pill";
export type Choice = Variant | "compare";
export interface Design {
  choice: Choice;
  /** Text size in percent, published as `--fs`. */
  fs: 100 | 125 | 150;
  compact: boolean;
  /** Outline every start target, so its size and edges show. */
  hits: boolean;
}

const CHOICES: { id: Choice; label: string }[] = [
  { id: "compare", label: "Side by side" },
  { id: "edge", label: "A edge" },
  { id: "split", label: "B split" },
  { id: "pill", label: "C pill" },
  { id: "current", label: "Today" },
];
const SIZES = [100, 125, 150] as const;
/** In `compare`, each startable lane draws one variant; any other lane has no start control. */
const BY_LANE: Record<string, Variant> = { ready: "edge", waiting: "split", needs_attention: "pill" };
export const VARIANT_NAME: Record<Variant, string> = { edge: "A · Right edge", split: "B · Hover split", pill: "C · Bigger pill", current: "Today" };

/** The design state an address asks for, or null when it carries no `start` parameter. */
export function readDesign(search: string): Design | null {
  const q = new URLSearchParams(search);
  if (!q.has("start")) return null;
  const choice = CHOICES.find((c) => c.id === q.get("start"))?.id ?? "compare";
  const fs = SIZES.find((s) => String(s) === q.get("fs")) ?? 100;
  return { choice, fs, compact: q.get("density") === "compact", hits: q.get("hits") === "1" };
}

/** `search` with the design state written back, every other parameter kept. */
export function writeDesign(search: string, d: Design): string {
  const q = new URLSearchParams(search);
  q.set("start", d.choice);
  q.set("fs", String(d.fs));
  if (d.compact) q.set("density", "compact");
  else q.delete("density");
  if (d.hits) q.set("hits", "1");
  else q.delete("hits");
  return `?${q.toString()}`;
}

/** The variant a card in `lane` draws. */
export const variantFor = (d: Design | null, lane: string): Variant => (!d ? "current" : d.choice === "compare" ? BY_LANE[lane] ?? "current" : d.choice);
/** The column header's tag in `compare`. */
export const laneTag = (d: Design | null, lane: string): Variant | null => (d?.choice === "compare" && BY_LANE[lane] ? BY_LANE[lane] : null);

export function DesignBar({ design, set }: { design: Design; set: (d: Design) => void }) {
  return (
    <div id="svbar" role="toolbar" aria-label="Start control variants">
      <span className="k">Start</span>
      {CHOICES.map((c) => (
        <button key={c.id} aria-pressed={design.choice === c.id} onClick={() => set({ ...design, choice: c.id })}>{c.label}</button>
      ))}
      <span className="sep" />
      <span className="k">Text</span>
      {SIZES.map((s) => (
        <button key={s} aria-pressed={design.fs === s} onClick={() => set({ ...design, fs: s })}>{s}%</button>
      ))}
      <span className="sep" />
      <button aria-pressed={design.compact} onClick={() => set({ ...design, compact: !design.compact })}>Compact</button>
      <button aria-pressed={design.hits} onClick={() => set({ ...design, hits: !design.hits })}>Targets</button>
    </div>
  );
}
