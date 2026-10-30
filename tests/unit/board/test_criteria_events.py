"""An event in the log re-evaluates the Start Criteria that name it, within seconds, instead of on the next 30 s pass."""

import shlex
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from starpulse.board import criteria
from starpulse.board.bin import board_worker
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.runs.run_events import STREAM as RUNS_STREAM

WITHIN_S = 5.0
DESCRIPTION = """## Start Criteria

```yaml
start_criteria:
- id: nightly
  kind: dagu_run
  dag: nightly
  since: 2026-10-01
```
"""
SCRIPT = """import json
open('runs.txt', 'a').write('x')
print(json.dumps([{"id": "nightly", "kind": "dagu_run", "status": "not-met",
                   "refresh": {"interval": 900, "on": ["run:nightly", "merge"]}}]))
"""


class Feed:
    """The part of the feed the events call: its pass, which asks the evaluator for each Waiting task as the real one does."""

    def __init__(self, evaluate: criteria.Evaluator) -> None:
        self._evaluate = evaluate

    def evaluate_criteria(self) -> None:
        self._evaluate("task-7", DESCRIPTION)


def _eventually(ready: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WITHIN_S
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def watched(tmp_path: Path):
    path = tmp_path / "evaluator.py"
    path.write_text(SCRIPT)
    evaluate = criteria.Evaluator(f"{shlex.quote(sys.executable)} {shlex.quote(str(path))} {{id}}", tmp_path)
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    evaluate("task-7", DESCRIPTION)
    stop = threading.Event()
    thread = board_worker.follow_criteria_events(Feed(evaluate), evaluate, log, stop)
    runs = tmp_path / "runs.txt"
    yield log, lambda: len(runs.read_text()) if runs.exists() else 0
    stop.set()
    thread.join(WITHIN_S)


def _run_ended(workflow: str, **extra: object) -> dict:
    return {"event": "StepFinished", "workflow": workflow, "run_id": "r1", "status": "succeeded", "time": 1.0, **extra}


def test_a_dagu_run_that_ends_re_evaluates_the_criterion_that_awaits_it_within_seconds(watched) -> None:
    log, count = watched

    log.publish(RUNS_STREAM, _run_ended("nightly"))

    assert _eventually(lambda: count() == 2)


def test_a_step_ending_or_another_dags_run_evaluates_nothing(watched) -> None:
    log, count = watched

    log.publish(RUNS_STREAM, _run_ended("nightly", step="build"))
    log.publish(RUNS_STREAM, _run_ended("other"))
    log.publish(RUNS_STREAM, {**_run_ended("nightly"), "status": "running"})
    log.publish(RUNS_STREAM, _run_ended("nightly"))

    assert _eventually(lambda: count() == 2)
    time.sleep(0.3)
    assert count() == 2


def test_a_merged_pull_request_re_evaluates_the_criteria_that_await_a_merge(watched) -> None:
    log, count = watched

    log.publish(
        MACHINE_STREAM, {"machine": "github-pull-request", "event": "PR_OPENED", "task": "t", "actor": "a", "time": 1.0}
    )
    log.publish(
        MACHINE_STREAM, {"machine": "github-pull-request", "event": "PR_MERGED", "task": "t", "actor": "a", "time": 1.0}
    )

    assert _eventually(lambda: count() == 2)
