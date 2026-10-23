"""The run ledger: each scheduler run's outcome, duration and resource peak, kept against its task in the history store."""

import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from starpulse._internal.scheduler.ledger import Ledger, RunRecord
from starpulse._internal.eventlog.event_log import EventLog


def _run(
    task: str = "TASK-1", tier: str = "standard", points: int = 8, cpu: float = 10, memory: float = 6
) -> RunRecord:
    return RunRecord(
        task, tier, points, "review", 120.0, {"cpu": cpu, "memory": memory, "sessions": 1, "review": points}
    )


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    return tmp_path / "starpulse-autopilot-runs.jsonl"


def _write_legacy(legacy: Path, *runs: RunRecord) -> None:
    legacy.write_text("".join(json.dumps(asdict(run)) + "\n" for run in runs))


def test_a_recorded_run_reads_back_against_its_task(log: EventLog, legacy: Path) -> None:
    first, other = _run("TASK-1"), _run("TASK-2")

    Ledger(log, legacy).record(first)
    Ledger(log, legacy).record(other)

    assert Ledger(log, legacy).runs("TASK-1") == [first]  # a new ledger reads the store back
    assert Ledger(log, legacy).runs() == [first, other]  # oldest first


def test_a_fresh_store_holds_no_runs(log: EventLog, legacy: Path) -> None:
    assert Ledger(log, legacy).runs() == []


def test_measured_demand_is_the_mean_peak_of_the_runs_of_that_tier_and_size(log: EventLog, legacy: Path) -> None:
    ledger = Ledger(log, legacy)
    for cpu, memory in ((10, 4), (20, 6), (30, 8)):
        ledger.record(_run(cpu=cpu, memory=memory))
    ledger.record(_run(tier="deep", cpu=90))  # another tier: not counted
    ledger.record(_run(points=2, cpu=90))  # another size: not counted

    assert ledger.measured("standard", 8, min_runs=3) == {"cpu": 20, "memory": 6, "sessions": 1, "review": 8}


def test_too_few_runs_measure_nothing(log: EventLog, legacy: Path) -> None:
    ledger = Ledger(log, legacy)
    ledger.record(_run())
    ledger.record(_run())

    assert ledger.measured("standard", 8, min_runs=3) is None


def test_an_unreadable_store_measures_nothing(tmp_path: Path, legacy: Path) -> None:
    unreadable = EventLog(f"sqlite:///{tmp_path / 'missing-dir' / 'history.sqlite'}")

    assert Ledger(unreadable, legacy).measured("standard", 8, min_runs=1) is None


def test_an_existing_file_is_imported_once_and_retired(log: EventLog, legacy: Path) -> None:
    _write_legacy(legacy, _run("TASK-1"), _run("TASK-2"))

    assert [run.task for run in Ledger(log, legacy).runs()] == ["TASK-1", "TASK-2"]

    assert not legacy.exists()
    assert legacy.with_name(legacy.name + ".imported").exists()


def test_a_file_written_after_the_import_is_ignored(log: EventLog, legacy: Path) -> None:
    _write_legacy(legacy, _run("TASK-1"))
    Ledger(log, legacy).runs()

    _write_legacy(legacy, _run("TASK-9"))

    assert [run.task for run in Ledger(log, legacy).runs()] == ["TASK-1"]


def test_an_import_interrupted_before_the_rename_adds_no_second_copy(log: EventLog, legacy: Path) -> None:
    _write_legacy(legacy, _run("TASK-1"))
    os.utime(legacy, (1_000_000.0, 1_000_000.0))
    Ledger(log, legacy).runs()
    legacy.with_name(legacy.name + ".imported").replace(legacy)  # the rename never happened

    assert [run.task for run in Ledger(log, legacy).runs()] == ["TASK-1"]
    assert not legacy.exists()


def test_imported_and_new_runs_measure_together(log: EventLog, legacy: Path) -> None:
    _write_legacy(legacy, _run(cpu=10), _run(cpu=20))
    ledger = Ledger(log, legacy)

    ledger.record(_run(cpu=30))

    assert ledger.measured("standard", 8, min_runs=3) == {"cpu": 20, "memory": 6, "sessions": 1, "review": 8}
