"""The lane changes a board's earlier history is imported from: one JSON object per line.

A line carries the fields of a `board:lanes` entry (`lane_events`) and the `event_id` that makes it land once:

    {"event_id": "ff971697-...", "task": "TASK-1095", "lane": "Done", "time": 1790289615.0}

`lane` is the board's status as its tracker spelled it and `time` the epoch second the task entered it. Blank lines are
skipped, and a field beyond these four is ignored, so an exporter may carry its own. `HistoryStore.import_lanes` folds
them into the store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

__all__ = ["Change", "read"]


class Change(NamedTuple):
    """A task entering `lane` at epoch `at`, under the `event_id` that names the move."""

    event_id: str
    task: str
    lane: str
    at: float


def _change(line: dict) -> Change:
    """The change `line` holds; `ValueError` names the field it lacks or spells wrongly."""
    for field in ("event_id", "task", "lane"):
        if not isinstance(line.get(field), str) or not line[field]:
            raise ValueError(f"`{field}` is not a non-empty string")
    at = line.get("time")
    if isinstance(at, bool) or not isinstance(at, int | float):
        raise ValueError("`time` is not a number of epoch seconds")
    return Change(line["event_id"], line["task"], line["lane"], float(at))


def read(path: Path) -> list[Change]:
    """Every change in the JSONL file at `path`, in file order; `ValueError` names the file and line of one it cannot read."""
    changes: list[Change] = []
    with path.open(encoding="utf-8") as lines:
        for number, raw in enumerate(lines, 1):
            if not raw.strip():
                continue
            try:
                line = json.loads(raw)
                if not isinstance(line, dict):
                    raise ValueError("the line is not a JSON object")
                changes.append(_change(line))
            except ValueError as error:  # JSONDecodeError is one
                raise ValueError(f"{path}:{number}: {error}") from error
    return changes
