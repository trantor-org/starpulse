"""`/api/analytics/steps` answers a 168 h window of every model request without holding every step as Python data at
once: the live fold of 330k steps took 830 MB over the telemetry history it reads (TASK-10788), a dict list and a
validated model list that only the 119 MB body outlives."""

from __future__ import annotations

import json
import re
import tracemalloc
from typing import Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.signals import Signal
from starpulse.flow_metrics.model.steps import session_steps
from starpulse.views.application.queries.responses import steps_response
from starpulse.views.model.encoding import encode

MB = 1024 * 1024
KEYS = TaskKeys(key=re.compile(r"TASK-\d+"), branch=re.compile(r"task-(\d+)"), key_format="TASK-{}")
NOW = 2_000_000.0
STEPS = 12_000
SESSIONS = 60
PEAK_PER_BODY_BYTE = 4  # the body, a join of its parts, and the parts themselves; a held list of step dicts is ~20


class _Log:
    """A `TelemetryLog` holding `found`."""

    def __init__(self, found: list[Signal]) -> None:
        self._found = found

    def read(self, since: float = 0.0) -> list[Signal]:
        return [s for s in self._found if s.time >= since]


def _signals(count: int) -> list[Signal]:
    found = []
    for n in range(count):
        session = f"session-{n % SESSIONS}"
        at = NOW - 7300 + n * 0.25 + (0.125 if n % 7 == 0 else 0.0)  # interleaved sessions, some equal times
        found.append(
            Signal(
                harness="claude-code",
                session=session,
                kind="request",
                time=at,
                key=f"k{n}",
                model="claude-sonnet-5-5",
                input=300 + n,
                output=40 + n % 90,
                cache_read=90_000 + n,
                seconds=1.5,
            )
        )
        if n % 3 == 0:
            found.append(
                Signal(
                    harness="claude-code",
                    session=session,
                    kind="tool",
                    time=at + 0.1,
                    key=f"t{n}",
                    name="Bash",
                    command=f"git -C /srv/trantor status --short {n}",
                    activities=("shell",),
                    seconds=0.2,
                )
            )
    return found


def _old_body(found: list[Signal]) -> bytes:
    window = [s for s in found if s.time >= NOW - 7200]
    return encode("session_steps", {"now": NOW, "window_s": 7200.0, "steps": session_steps(window, KEYS, None)})


def test_the_steps_body_is_the_one_a_list_of_every_step_encodes_to() -> None:
    found = _signals(900)

    body, status = steps_response(_Log(found), {"hours": ["2"]}, KEYS, NOW)

    assert status == 200
    assert body == _old_body(found)
    steps: list[dict[str, Any]] = json.loads(body)["steps"]
    assert 0 < len(steps) <= 900
    assert [s["at"] for s in steps] == sorted(s["at"] for s in steps)


def test_the_traced_peak_of_a_steps_fold_stays_within_a_few_bodies() -> None:
    found = _signals(STEPS)
    log = _Log(found)
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        body, status = steps_response(log, {"hours": ["2"]}, KEYS, NOW)
        peak = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()

    assert status == 200
    assert peak < PEAK_PER_BODY_BYTE * len(body), (
        f"the fold of {STEPS} steps peaked at {peak / MB:.1f} MB for a {len(body) / MB:.1f} MB body"
    )
