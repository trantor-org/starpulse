"""The runs stream contract: one entry when a workflow run or one of its steps starts or ends.

`starpulse emit` writes it from any scheduler hook or script, so a workflow needs no adapter to be seen.
Emission is fail-open (`starpulse.streams.StreamProducer`): a missing entry means the emit failed, never that the
run did not happen.

Each entry carries `event_id` plus these fields (absent when empty): `time` (epoch seconds), `phase`
(`start` or `end`), `workflow`, `run_id`, `status` (one of `contracts.RunStatus`), and, for a step's entry,
`step` (its name) and `depends` (a JSON list of the step names it waits on).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from starpulse.streams import StreamProducer, endpoint_from_url

# Redis is reached at RUNS_REDIS_HOST/_PORT plus the shared REDIS_PASSWORD, or at REDIS_URL.
STREAM = "runs:events"
REDIS_ENV_PREFIX = "RUNS"
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
) -> dict[str, Any]:
    """One stream entry; `step` and `depends` make it a step's rather than the run's."""
    return {
        "time": now,
        "phase": phase,
        "workflow": workflow,
        "run_id": run_id,
        "status": status,
        **({"step": step} if step else {}),
        **({"depends": depends} if depends else {}),
    }


def producer(environ: Mapping[str, str]) -> StreamProducer:
    """The producer for the Redis `environ` names: `REDIS_URL` when set, else the `RUNS_REDIS_*` variables."""
    if url := environ.get("REDIS_URL"):
        return StreamProducer(stream=STREAM, **endpoint_from_url(url, environ.get("REDIS_PASSWORD")))
    return StreamProducer.from_env(REDIS_ENV_PREFIX, stream=STREAM)
