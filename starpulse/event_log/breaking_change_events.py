"""The `breaking-change:events` stream: a commit that broke the default branch, and the postmortem that closes it.

A producer posts a `RECORDED` CloudEvent per detection (subject: the merge commit; `data`: `detector`, `outcome`, and
optionally `pr`, `task`, `evidence`) and a `POSTMORTEMED` one (subject: the commit; `data.task`: the postmortem task).
StarPulse names no detector and no outcome: both are the producer's strings.
"""

from __future__ import annotations

from typing import Any

STREAM = "breaking-change:events"
#: The CloudEvents `type` of one detector naming one commit as a break.
RECORDED = "BreakingChangeRecorded"
#: The CloudEvents `type` that closes a commit's row once its postmortem task exists.
POSTMORTEMED = "BreakingChangePostmortemed"
EVENTS = frozenset({RECORDED, POSTMORTEMED})


def entry(
    event: str,
    commit: str,
    at: float,
    source: str,
    *,
    detector: str | None = None,
    outcome: str | None = None,
    pr: int | None = None,
    task: str | None = None,
    evidence: str | None = None,
) -> dict[str, Any]:
    """The fields of a breaking-change entry; a field the producer left out is absent."""
    optional = {"detector": detector, "outcome": outcome, "pr": pr, "task": task, "evidence": evidence}
    return {
        "event": event,
        "commit": commit,
        "time": at,
        "source": source,
        **{name: value for name, value in optional.items() if value is not None},
    }
