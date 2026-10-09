"""A task's stays in the Board's lanes, folded from the lane changes a history keeps."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

__all__ = ["Dwell", "LaneRow", "LaneStays", "Stay", "lane_stays"]

#: A lane change as the history keeps it: `(task, at, from, to)`, `at` in epoch seconds.
LaneRow = tuple[str, float, str | None, str]


class Stay(NamedTuple):
    """One task's stay in a lane from `began` to `ended`, which is None while it is still there."""

    task: str
    lane: str
    began: float
    ended: float | None


class Dwell(NamedTuple):
    """The stays of one lane that ended in a window: how many, their lengths added up, and the longest."""

    visits: int
    total: float
    longest: float


@dataclass(frozen=True)
class LaneStays:
    """What `stay_health` reads of a lane history for one window, without every stay the history ever kept.

    `ended` is each lane's stays that ended at or after the window's start, as a `Dwell`. `entered` is how many stays
    began in each lane inside the window. `going` is each lane's stays still in it, as a `Dwell` of their lengths to
    now (more lanes than a state that is not final needs are harmless). `stuck` are the stays still going that have
    lasted the stuck threshold or nearly (more than a state that is neither initial nor final needs are harmless; the
    reader checks each). `open_by_lane` is how many tasks are in each lane now, and `lanes` every lane the history has
    recorded. All but `stuck` are one row per lane, so the read grows with the lanes and the stays that are stuck, not
    with the stays the window holds or the tasks in flight.
    """

    ended: Mapping[str, Dwell]
    entered: Mapping[str, int]
    going: Mapping[str, Dwell]
    stuck: Sequence[Stay]
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


def lane_stays(rows: Iterable[LaneRow], *, start: float, now: float, stuck_s: float) -> LaneStays:
    """What `stay_health` reads of the stays `rows` hold for the window from `start` to `now`, the tasks now in each
    lane and the lanes in the order they first appear; `stuck_s` is how long a stay lasts to be listed as stuck."""
    stays = list(_stays(rows))
    lengths: dict[str, list[float]] = defaultdict(list)
    for stay in stays:
        if stay.ended is not None and stay.ended >= start:
            lengths[stay.lane].append(stay.ended - stay.began)
    going: dict[str, list[float]] = defaultdict(list)
    for stay in stays:
        if stay.ended is None:
            going[stay.lane].append(now - stay.began)
    return LaneStays(
        {lane: Dwell(len(found), sum(found), max(found)) for lane, found in lengths.items()},
        Counter(stay.lane for stay in stays if start <= stay.began <= now),
        {lane: Dwell(len(found), sum(found), max(found)) for lane, found in going.items()},
        [stay for stay in stays if stay.ended is None and now - stay.began >= stuck_s],
        Counter(stay.lane for stay in stays if stay.ended is None),
        list(dict.fromkeys(s.lane for s in stays)),
    )
