"""A task's stays in the Board's lanes, folded from the lane changes a history keeps."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

__all__ = ["Dwell", "LaneRow", "LaneStays", "Stay"]

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
