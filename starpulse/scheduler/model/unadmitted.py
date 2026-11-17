"""The hours the autopilot could not admit, by cause, derived from the change events.

The switch outranks the quiet hours, which outrank a usage-limit pause. A quiet-hours edge is not an event: it is read
from the window and its edits. Before the first recorded change a value reads as the current one.
"""

import itertools
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from starpulse.event_log.event_log import Entry
from starpulse.scheduler.model.quiet_hours import QuietHours

CAUSES = ("switched off", "quiet hours", "usage limit")
_HOUR_S = 3600.0


def _history(entries: Iterable[Entry], kind: str, start: float, current: Any) -> list[tuple[float, Any]]:
    """The value of `kind` as `(since, value)` rows from `start`: what it was then, then each change."""
    changes = [(e.at, e.fields["new"]) for e in entries if e.fields["kind"] == kind]
    before = [value for at, value in changes if at <= start]
    after = [(at, value) for at, value in changes if at > start]
    if before:
        first = before[-1]
    else:
        first = next((e.fields["old"] for e in entries if e.fields["kind"] == kind), current)
    return [(start, first), *after]


def _value(history: list[tuple[float, Any]], at: float) -> Any:
    return history[bisect_right([since for since, _ in history], at) - 1][1]


def _edges(window: QuietHours, start: float, now: float) -> Iterable[float]:
    zone = ZoneInfo(window.timezone)
    day = datetime.fromtimestamp(start, zone).date() - timedelta(days=1)
    while datetime.combine(day, time(), zone).timestamp() <= now:
        for clock in (window.start, window.end):
            yield datetime.combine(day, time.fromisoformat(clock), zone).timestamp()
        day += timedelta(days=1)


def unadmitted_hours(
    entries: Sequence[Entry], *, now: float, window_s: float, enabled: bool, quiet: dict[str, Any] | None
) -> dict[str, float]:
    """Hours of the last `window_s` seconds before `now` in which admission was held, by cause (`CAUSES`); `enabled` and
    `quiet` are the current switch and window, which hold wherever no event says otherwise."""
    start = now - window_s
    switch = _history(entries, "enabled", start, enabled)
    windows = _history(entries, "quiet_hours", start, quiet)
    pauses = [
        (e.at, e.fields["new"]) for e in entries if e.fields["kind"] == "usage_limit" and e.fields.get("selected", True)
    ]
    cuts = {start, now, *(since for since, _ in switch), *(since for since, _ in windows)}
    for _, raw in windows:
        if raw is not None:
            cuts.update(_edges(QuietHours(**raw), start, now))
    for begun, until in pauses:
        cuts.update((begun, until))
    edges = sorted(cut for cut in cuts if start <= cut <= now)
    hours = dict.fromkeys(CAUSES, 0.0)
    for began, ended in itertools.pairwise(edges):
        middle = (began + ended) / 2
        raw = _value(windows, middle)
        if not _value(switch, middle):
            cause = CAUSES[0]
        elif raw is not None and QuietHours(**raw).contains(middle):
            cause = CAUSES[1]
        elif any(begun <= middle < until for begun, until in pauses):
            cause = CAUSES[2]
        else:
            continue
        hours[cause] += (ended - began) / _HOUR_S
    return hours
