"""A task's stays in the Board's lanes, folded from the lane changes a history keeps."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

__all__ = ["LaneRow", "LaneStays", "Stay", "lane_stays"]

#: A lane change as the history keeps it: `(task, at, from, to)`, `at` in epoch seconds.
LaneRow = tuple[str, float, str | None, str]


class Stay(NamedTuple):
    """One task's stay in a lane from `began` to `ended`, which is None while it is still there."""

    task: str
    lane: str
    began: float
    ended: float | None


@dataclass(frozen=True)
class LaneStays:
    """What `stay_health` reads of a lane history, enough to answer for a window without every stay ever kept.

    `stays` hold every stay that ended in the window or is still going in a state that is not final, and every entry
    into a final state in it; more are harmless. `open_by_lane` is how many tasks are in each lane now, and `lanes`
    every lane the history has recorded.
    """

    stays: Sequence[Stay]
    open_by_lane: Mapping[str, int]
    lanes: Sequence[str]


def _stays(rows: Iterable[LaneRow]) -> Iterable[Stay]:
    """Each task's stays, oldest first; the stay it is still in has no end."""
    by_task: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for task, at, _old, new in rows:
        by_task[task].append((at, new))
    for task, changes in by_task.items():
        changes.sort(key=lambda change: change[0])
        for (start, lane), later in zip(changes, [*changes[1:], None]):
            yield Stay(task, lane, start, later[0] if later else None)


def lane_stays(rows: Iterable[LaneRow]) -> LaneStays:
    """Every stay `rows` hold, with the tasks now in each lane and the lanes in the order they first appear."""
    stays = list(_stays(rows))
    return LaneStays(
        stays, Counter(stay.lane for stay in stays if stay.ended is None), list(dict.fromkeys(s.lane for s in stays))
    )
