"""The run ledger: each scheduler run's outcome, duration and resource peak, kept against its task in the history store."""

from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.scheduler.model.ledger import Ledger, RunRecord


def _run(
    task: str = "TASK-1", tier: str = "standard", points: int = 8, cpu: float = 10, memory: float = 6
) -> RunRecord:
    return RunRecord(
        task, tier, points, "review", 120.0, {"cpu": cpu, "memory": memory, "sessions": 1, "review": points}
    )


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


def test_a_recorded_run_reads_back_against_its_task(log: EventLog) -> None:
    first, other = _run("TASK-1"), _run("TASK-2")

    Ledger(log).record(first)
    Ledger(log).record(other)

    assert Ledger(log).runs("TASK-1") == [first]  # a new ledger reads the store back
    assert Ledger(log).runs() == [first, other]  # oldest first


def test_a_fresh_store_holds_no_runs(log: EventLog) -> None:
    assert Ledger(log).runs() == []


def test_measured_demand_is_the_mean_peak_of_the_runs_of_that_tier_and_size(log: EventLog) -> None:
    ledger = Ledger(log)
    for cpu, memory in ((10, 4), (20, 6), (30, 8)):
        ledger.record(_run(cpu=cpu, memory=memory))
    ledger.record(_run(tier="deep", cpu=90))  # another tier: not counted
    ledger.record(_run(points=2, cpu=90))  # another size: not counted

    assert ledger.measured("standard", 8, min_runs=3) == {"cpu": 20, "memory": 6, "sessions": 1, "review": 8}


def test_too_few_runs_measure_nothing(log: EventLog) -> None:
    ledger = Ledger(log)
    ledger.record(_run())
    ledger.record(_run())

    assert ledger.measured("standard", 8, min_runs=3) is None


def test_an_unreadable_store_measures_nothing(tmp_path: Path) -> None:
    unreadable = EventLog(f"sqlite:///{tmp_path / 'missing-dir' / 'history.sqlite'}")

    assert Ledger(unreadable).measured("standard", 8, min_runs=1) is None
