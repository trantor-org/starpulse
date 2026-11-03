"""The autopilot's decision log, kept in the store so a gauge reads StarPulse and not the service manager's journal."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

#: The worker-state key the log is kept under.
KEY = "scheduler.decision_log"
#: Days of verdicts and starts kept; older ones are dropped at the next note.
RETENTION_DAYS = 90
EMPTY: dict[str, Any] = {"days": {}, "starts": [], "restored_at": None}


def note(
    log: dict[str, Any], at: float, *, verdicts: Iterable[str] = (), started: str | None = None, restored: bool = False
) -> dict[str, Any]:
    """`log` with this pass's `verdicts` (`admitted` or `refused/<gate>`) counted under the local day of `at`, the task
    it `started`, and the first `restored` time; it drops what is past `RETENTION_DAYS`. `log` itself is unchanged."""
    cutoff = at - RETENTION_DAYS * 86400
    cutoff_day = datetime.fromtimestamp(cutoff).date().isoformat()
    days = {day: dict(counts) for day, counts in log["days"].items() if day >= cutoff_day}
    today = days.setdefault(datetime.fromtimestamp(at).date().isoformat(), {})
    for verdict in verdicts:
        today[verdict] = today.get(verdict, 0) + 1
    starts = [start for start in log["starts"] if start["at"] >= cutoff]
    if started is not None:
        starts.append({"task": started, "at": at})
    first = log["restored_at"] if log["restored_at"] is not None else (at if restored else None)
    return {"days": {day: counts for day, counts in days.items() if counts}, "starts": starts, "restored_at": first}
