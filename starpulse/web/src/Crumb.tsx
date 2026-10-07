// The canvas breadcrumb: where the Star Map is drilled (Board › In Progress › machine), plain text
// at the map's top-left. The current level is text; every level above it backs the map out to it.
import { Fragment } from "react";
import type { BoardState } from "./hud";
import { pathKey, type Level, type Path } from "./levels";

const name = (l: Level, states: BoardState[]) =>
  l.kind === "board" ? "Board" : l.kind === "state" ? (states.find((s) => s.id === l.id)?.name ?? l.id) : l.kind === "machine" ? l.flow : "DAGs";

/** One entry per drilled level: its name and the path down to it. */
export const crumbs = (path: Path, states: BoardState[]) => path.map((l, i) => ({ label: name(l, states), path: path.slice(0, i + 1) }));

export function Crumb({ path, states, open }: { path: Path; states: BoardState[]; open: (p: Path) => void }) {
  const levels = crumbs(path, states);
  return (
    <nav id="crumb" aria-label="Where the map is drilled">
      {levels.map((c, i) => (
        <Fragment key={pathKey(c.path)}>
          {i > 0 && <span className="sep" aria-hidden="true">›</span>}
          {i === levels.length - 1 ? <span className="here" aria-current="location">{c.label}</span> : <button type="button" onClick={() => open(c.path)}>{c.label}</button>}
        </Fragment>
      ))}
    </nav>
  );
}
