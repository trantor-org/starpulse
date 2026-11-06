from __future__ import annotations

from pathlib import Path

import pytest

from starpulse.event_log.event_log import EventLog
from starpulse.runs.application.queries.projection import PROJECTION
from starpulse.runs.application.queries.reconcile import RESYNC, Reconcile


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}")


def _dag(name: str, status: str, run_id: str) -> dict:
    return {"name": name, "status": status, "runId": run_id}


def _resyncs(log: EventLog) -> list[str]:
    return [entry.fields["instance"] for entry in log.tail(RESYNC, after=0).poll()]


def test_a_source_that_lists_a_run_the_projection_lacks_is_corrected_with_a_resync(log: EventLog) -> None:
    log.put_state_entry(PROJECTION, "dagu", {"dags": [_dag("nightly", "succeeded", "r1")]})
    reconcile = Reconcile(log, {"dagu": lambda: [_dag("nightly", "running", "r2")]})

    assert reconcile.run() == (1, 1)
    assert _resyncs(log) == ["dagu"]


def test_a_source_that_agrees_with_the_projection_is_sampled_and_left_alone(log: EventLog) -> None:
    log.put_state_entry(PROJECTION, "dagu", {"dags": [_dag("nightly", "succeeded", "r1")]})
    reconcile = Reconcile(log, {"dagu": lambda: [_dag("nightly", "succeeded", "r1")]})

    assert reconcile.run() == (0, 1)
    assert _resyncs(log) == []


def test_a_source_that_cannot_be_read_is_not_counted_as_a_miss(log: EventLog) -> None:
    def down() -> list[dict]:
        raise OSError("refused")

    assert Reconcile(log, {"dagu": down}).run() == (0, 0)
    assert _resyncs(log) == []
