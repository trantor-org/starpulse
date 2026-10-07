// The canvas breadcrumb: where the Star Map is drilled (Board › In Progress › machine), plain text
// at the map's top-left. The current level is text; every level above it backs the map out to it.
import { Fragment } from "react";
import type { BoardState } from "./hud";
import { pathKey, type Level, type Path } from "./levels";

const name = (l: Level, states: BoardState[]) =>
  l.kind === "board" ? "Board" : l.kind === "state" ? (states.find((s) => s.id === l.id)?.name ?? l.id) : l.kind === "machine" ? l.flow : "DAGs";

/** One entry per drilled level: its name and the path down to it. */
export const crumbs = (path: Path, states: BoardState[]) => path.map((l, i) => ({ label: name(l, states), path: path.slice(0, i + 1) }));

export function Crumb({ path, states, sources, open }: { path: Path; states: BoardState[]; sources?: Record<string, string>; open: (p: Path) => void }) {
  const levels = crumbs(path, states);
  // a mapped machine names its source after it, in blue
  const named = (i: number) => {
    const l = path[i], src = l.kind === "machine" ? sources?.[l.flow] : undefined;
    return <>{levels[i].label}{src && <span className="src" data-src={src} title={`mapped from ${src}`} />}</>;
  };
  return (
    <nav id="crumb" aria-label="Where the map is drilled">
      {levels.map((c, i) => (
        <Fragment key={pathKey(c.path)}>
          {i > 0 && <span className="sep" aria-hidden="true">›</span>}
          {i === levels.length - 1 ? <span className="here" aria-current="location">{named(i)}</span> : <button type="button" onClick={() => open(c.path)}>{named(i)}</button>}
        </Fragment>
      ))}
    </nav>
  );
}
