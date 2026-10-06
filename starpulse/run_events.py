"""The runs stream contract: one entry when a workflow run or one of its steps starts or ends.

`starpulse emit` writes it from any scheduler hook or script, so a workflow needs no adapter to be seen.
Emission is fail-open (`EventLog.append` never raises): a missing entry means the emit failed, never that the
run did not happen.

Each entry carries `event_id` plus these fields (absent when empty): `time` (epoch seconds), `phase`
(`start` or `end`), `workflow`, `run_id`, `status` (one of `contracts.RunStatus`), and, for a step's entry,
`step` (its name) and `depends` (a JSON list of the step names it waits on). An entry the HTTP ingest wrote also
carries `instance`, the runs adapter instance whose token pushed it: it is that instance's, so another instance's
reader ignores it.
"""

from __future__ import annotations

from typing import Any

STREAM = "runs:events"
PHASES = ("start", "end")


def entry(
    phase: str,
    workflow: str,
    run_id: str,
    status: str,
    *,
    now: float,
    step: str | None = None,
    depends: list[str] | None = None,
    instance: str | None = None,
) -> dict[str, Any]:
    """One stream entry; `step` and `depends` make it a step's rather than the run's, `instance` an ingested one's."""
    return {
        "time": now,
        "phase": phase,
        "workflow": workflow,
        "run_id": run_id,
        "status": status,
        **({"step": step} if step else {}),
        **({"depends": depends} if depends else {}),
        **({"instance": instance} if instance else {}),
    }
