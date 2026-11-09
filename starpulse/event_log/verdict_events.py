"""The task:verdicts stream contract: one entry per verdict a qa lens gives a task in a round.

A verdict is `PASS` or `CHANGES` (with the `reason` it gives) for one `lens` in one `round` of a task's qa phase; every
entry is kept and none supersedes another. An entry carries `task`, `lens`, `round`, `outcome`, `reason`, `time` (epoch
seconds) and the `source` producer that posted it. A producer posts one as a CloudEvent of type `EVENT` through the ingest.
"""

from __future__ import annotations

from typing import Any

STREAM = "task:verdicts"
#: The CloudEvents `type` of a verdict, which carries `lens`, `round`, `outcome` and `reason` in `data`.
EVENT = "VerdictRecorded"


def entry(
    task: str, lens: str, round: int, outcome: str, reason: str, at: float, source: str = ""
) -> dict[str, Any]:
    """The fields of a verdict entry; `source` only when a producer posted it."""
    return {
        "task": task,
        "lens": lens,
        "round": round,
        "outcome": outcome,
        "reason": reason,
        "time": at,
        **({"source": source} if source else {}),
    }
