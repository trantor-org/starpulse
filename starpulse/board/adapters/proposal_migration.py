"""Move a native board's Proposed tasks to their own `PROP-N` ids and back, keeping every old id as an alias."""

from __future__ import annotations

import json
import re
from pathlib import Path

from starpulse.board.adapters.native import (
    _allocating,
    _find,
    _next_id,
    _reidentified,
    _Retired,
    _split_record,
)
from starpulse.machine_engine.model.transitions import lane_id


def migrate(
    root: Path, proposal_prefix: str, proposed: str, alias_map: Path, file_name: str = "title"
) -> dict[str, str]:
    """Give each Proposed task under `root` the next `proposal_prefix` id, oldest task number first, and write the map
    of old id to new id to `alias_map`: the answer is that map. A task already numbered with the prefix is left alone,
    so a rerun finishes what an interrupted one began."""
    done: dict[str, str] = json.loads(alias_map.read_text()) if alias_map.exists() else {}
    with _allocating(root):
        for old in _proposals(root, proposal_prefix, proposed):
            if (path := _find(root, old)) is None:
                continue
            new = _next_id(root, proposal_prefix, _Retired())
            if (moved := _reidentified(root, path, new, file_name)).ok:
                done[old] = new
                alias_map.write_text(json.dumps(done, indent=1, sort_keys=True))
            else:
                raise RuntimeError(moved.output)
    return done


def reverse(root: Path, alias_map: Path, file_name: str = "title") -> dict[str, str]:
    """Give each task `alias_map` lists its old id back: the answer is the map entries restored. A proposal promoted
    since, which no file holds under its new id, is left under its task number."""
    restored: dict[str, str] = {}
    with _allocating(root):
        for old, new in json.loads(alias_map.read_text()).items():
            if (path := _find(root, new)) is None or _held_id(path) != new:
                continue
            if (moved := _reidentified(root, path, old, file_name, restore=True)).ok:
                restored[old] = new
            else:
                raise RuntimeError(moved.output)
    return restored


def _held_id(path: Path) -> str:
    return str(_split_record(path.read_text())[0].get("id") or "")


def _proposals(root: Path, prefix: str, proposed: str) -> list[str]:
    """The ids of the Proposed tasks under `root` that do not carry `prefix`, lowest number first."""
    ids = []
    for path in (root / "tasks").glob("*.md"):
        frontmatter, _ = _split_record(path.read_text())
        task = str(frontmatter.get("id") or "")
        if lane_id(str(frontmatter.get("status") or "")) == proposed and not task.startswith(f"{prefix}-"):
            ids.append(task)
    return sorted(ids, key=lambda task: int((re.search(r"(\d+)$", task) or [0, 0])[1]))
