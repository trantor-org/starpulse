// What the orbit card's details panel says of a focused body: the second tier of detail, past the hover tip, from the
// numbers the level already answers (each end's count, the time in each state, the open runs and the latest arrivals).
import type { LevelResponse } from "./levelData";
import type { OrbitScene } from "./orbit";
import type { Hover } from "./orbitDraw";

const DAY = 86400, SHOWN = 5;

export interface DetailRow { label: string; value: string; col?: string; warn?: boolean }
export interface Details { kind: string; name: string; facts: [string, string][]; sections: { title: string; rows: DetailRow[]; more: number }[] }

/** A span of seconds in minutes under an hour, hours under a day, else days, to one place. */
export function duration(s: number): string {
  const [n, unit] = s < 3600 ? [s / 60, "m"] : s < DAY ? [s / 3600, "h"] : [s / DAY, "d"];
  return `${Math.round(n * 10) / 10}${unit}`;
}

const pct = (x: number) => `${Math.round(x * 100)}%`;
const section = (title: string, rows: DetailRow[]) => ({ title, rows: rows.slice(0, SHOWN), more: Math.max(0, rows.length - SHOWN) });

/** The details of a focused source or sun; an empty list is left out rather than shown empty. */
export function focusDetails(h: Hover, level: LevelResponse, scene: OrbitScene, name: (state: string) => string): Details {
  const days = Math.round(level.window_s / DAY), ago = (at: number) => `${duration(level.now - at)} ago`;
  const body = (id: string) => scene.sources.find((b) => b.id === id);
  const end = (id: string) => scene.ends.find((u) => u.id === id);
  const latest = (keep: (a: LevelResponse["arrivals"][number]) => boolean, label: (a: LevelResponse["arrivals"][number]) => DetailRow) =>
    level.arrivals.filter(keep).reverse().map(label);
  const sections = (list: { title: string; rows: DetailRow[]; more: number }[]) => list.filter((x) => x.rows.length);

  if (h.kind === "source") {
    const s = level.sources.find((x) => x.id === h.b.id)!, ended = Object.values(s.ended).reduce((a, n) => a + n, 0);
    const drift = s.drift && (s.drift.added.length || s.drift.removed.length) ? [["Drift", [...s.drift.added.map((a) => `+${a}`), ...s.drift.removed.map((r) => `−${r}`)].join(" ")] as [string, string]] : [];
    return {
      kind: s.shared ? "source" : "source · unattributed",
      name: h.b.name,
      facts: [
        ["Open now", `${s.wip}`], ["Ended", `${ended} in ${days} days`],
        ...level.level.terminals.map((t) => [name(t.id), `${s.ended[t.id] ?? 0} · ${pct(s.terminal_share[t.id] ?? 0)}`] as [string, string]),
        ...drift,
      ],
      sections: sections([
        section("Time in each state", Object.entries(s.dwell).sort((a, b) => b[1].task_s - a[1].task_s).map(([id, d]) => ({
          label: name(id), value: `${pct(s.time_share[id] ?? 0)} · ${d.visits} stays${d.mean_s == null ? "" : ` · mean ${duration(d.mean_s)}`}`,
        }))),
        section("Open runs, oldest first", level.aging.runs.filter((r) => r.source === s.id).map((r) => ({ label: r.task, value: `${name(r.state)} · ${duration(r.age_s)}`, warn: r.over }))),
        section("Latest arrivals", latest((a) => a.source === s.id, (a) => ({ label: name(a.state), value: ago(a.at), col: end(a.state)?.col }))),
      ]),
    };
  }

  const u = h.u, id = u.id;
  if (scene.ends.includes(u)) {
    const n = level.orbit.terminals[id]?.ended ?? 0, all = Object.values(level.orbit.terminals).reduce((a, t) => a + t.ended, 0);
    return {
      kind: `terminal · ${u.role}`,
      name: u.name,
      facts: [["Ended here", `${n} in ${days} days`], ["Share of all ended", pct(all ? n / all : 0)], ["Last 24 hours", `${level.arrivals.filter((a) => a.state === id && a.at >= level.now - DAY).length}`]],
      sections: sections([
        section("By source", level.sources.filter((s) => s.ended[id]).sort((a, b) => b.ended[id] - a.ended[id]).map((s) => ({
          label: body(s.id)?.name ?? s.id, value: `${s.ended[id]} · ${pct(n ? s.ended[id] / n : 0)}`, col: body(s.id)?.col,
        }))),
        section("Latest arrivals", latest((a) => a.state === id, (a) => ({ label: body(a.source)?.name ?? a.source, value: ago(a.at), col: body(a.source)?.col }))),
      ]),
    };
  }

  const stays = level.time_in_state.find((t) => t.id === id);
  return {
    kind: "working state",
    name: u.name,
    facts: [
      ["Open now", `${level.wip.states[id] ?? 0}`], ["Task-days", `${Math.round((level.orbit.working[id]?.task_s ?? 0) / DAY)} in ${days} days`],
      ...(stays ? [["Stays", `${stays.visits}${stays.mean_s == null ? "" : ` · mean ${duration(stays.mean_s)}`}`] as [string, string]] : []),
    ],
    sections: sections([
      section("By source", level.sources.filter((s) => s.dwell[id]).sort((a, b) => b.dwell[id].task_s - a.dwell[id].task_s).map((s) => ({
        label: body(s.id)?.name ?? s.id, value: `${pct(s.time_share[id] ?? 0)} of its time${s.dwell[id].mean_s == null ? "" : ` · mean ${duration(s.dwell[id].mean_s!)}`}`, col: body(s.id)?.col,
      }))),
      section("Open runs here, oldest first", level.aging.runs.filter((r) => r.state === id).map((r) => ({ label: r.task, value: `${body(r.source)?.name ?? r.source} · ${duration(r.age_s)}`, warn: r.over }))),
    ]),
  };
}
